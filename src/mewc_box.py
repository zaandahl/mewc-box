"""Draw/sort derived copies while preserving input paths and original bytes."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile

from PIL import Image

DEFAULTS = dict(INPUT_DIR="/images", MD_FILE="md_out.json", OUTPUT_DIR="boxed",
                DRAW=True, SUBFOLDER=True, SORT_POLICY="mixed", BLANK_DIR="blank",
                MIXED_DIR="mixed", OVERLAP=0.3, EDGE_DIST=0.02, MIN_EDGES=0,
                UPPER_CONF=0.9, LOWER_CONF=0.05, SUPPRESSION_POLICY="category-confidence-v1")


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, int)) and str(value).lower() in {"true", "1", "false", "0"}:
        return str(value).lower() in {"true", "1"}
    raise ValueError(f"invalid boolean: {value!r}")


def safe_path(root, relative):
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError("image/directory path must be POSIX relative")
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(p in ("..", ".", "") for p in relative.split("/")):
        raise ValueError(f"unsafe relative path: {relative!r}")
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError(f"path escapes its root: {relative}")
    return result


def atomic_write(path, writer):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".mewc-", suffix=path.suffix, dir=path.parent)
    os.close(fd)
    try:
        writer(Path(name))
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def sort_category(eligible, categories, config):
    if not eligible:
        return config["BLANK_DIR"]
    found = {str(d["category"]) for d in eligible}
    if len(found) == 1:
        return categories[next(iter(found))]
    policy = config["SORT_POLICY"]
    if policy == "mixed":
        return config["MIXED_DIR"]
    if policy == "highest_confidence":
        confidence = max(float(d["conf"]) for d in eligible)
        winners = {str(d["category"]) for d in eligible if float(d["conf"]) == confidence}
        if len(winners) == 1:
            return categories[next(iter(winners))]
        raise ValueError("mixed categories tie at highest confidence; choose SORT_POLICY=mixed")
    raise ValueError("mixed eligible categories require explicit SORT_POLICY=mixed or highest_confidence")


def render(image, detections, lower_conf):
    from megadetector.visualization.visualization_utils import render_detection_bounding_boxes
    render_detection_bounding_boxes(detections, image, confidence_threshold=float(lower_conf))


def run(config, process=None, renderer=render):
    if process is None:
        from lib_tools import process_detections
        process = process_detections
    config = {**DEFAULTS, **config}
    draw, subfolder = parse_bool(config["DRAW"]), parse_bool(config["SUBFOLDER"])
    if config["SORT_POLICY"] not in {"error", "mixed", "highest_confidence"}:
        raise ValueError("SORT_POLICY must be error, mixed, or highest_confidence")
    root = Path(config["INPUT_DIR"]).resolve()
    output = safe_path(root, config["OUTPUT_DIR"])
    if output == root:
        raise ValueError("OUTPUT_DIR must differ from INPUT_DIR")
    if safe_path(root, config["MD_FILE"]).is_relative_to(output):
        raise ValueError("detector artifact lies in OUTPUT_DIR")
    report = dict(schema_version=1, stage="box", complete=False, draw=draw, subfolder=subfolder,
                  sort_policy=config["SORT_POLICY"], suppression_policy=config["SUPPRESSION_POLICY"], images=[], errors=[])
    data = json.loads(safe_path(root, config["MD_FILE"]).read_text())
    for item in data["images"]:
        if safe_path(root, item["file"]).is_relative_to(output):
            raise ValueError("source image lies in OUTPUT_DIR")
    try:
        categories = {str(key): value for key, value in data["detection_categories"].items()}
        names = [item["file"] for item in data["images"]]
        if len(names) != len(set(names)):
            raise ValueError("duplicate detector image paths")
        for item in data["images"]:
            entry = dict(source_file=item.get("file"), status="error")
            report["images"].append(entry)
            try:
                source = safe_path(root, item["file"])
                if source.is_relative_to(output):
                    raise ValueError("source image lies in OUTPUT_DIR")
                valid = process(item, config["OVERLAP"], config["EDGE_DIST"], config["MIN_EDGES"], config["UPPER_CONF"], config["LOWER_CONF"], policy=config["SUPPRESSION_POLICY"])
                eligible = [d for d, keep in zip(item["detections"], valid) if keep]
                entry["eligible_detection_indices"] = [i for i, keep in enumerate(valid) if keep]
                directory = safe_path(output, sort_category(eligible, categories, config)) if subfolder else output
                destination = safe_path(directory, item["file"])
                entry["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
                if draw and eligible:
                    with Image.open(source) as image:
                        image.load()
                        renderer(image, eligible, config["LOWER_CONF"])
                        options = {key: image.info[key] for key in ("exif", "icc_profile") if key in image.info}
                        atomic_write(destination, lambda temp: image.save(temp, **options))
                    entry["status"] = "rendered"
                else:
                    atomic_write(destination, lambda temp: shutil.copy2(source, temp))
                    entry["status"] = "copied"
                entry["output_file"] = str(destination.relative_to(root))
                entry["output_sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
            except Exception as error:
                entry["status"] = "error"
                entry["error"] = str(error)
        report["counts"] = {status: sum(e["status"] == status for e in report["images"]) for status in ("rendered", "copied", "error")}
        report["complete"] = report["counts"]["error"] == 0
    except Exception as error:
        report["errors"].append(str(error))
        if not report["images"]:
            report["images"] = [dict(source_file=item.get("file"), status="not_processed",
                                     error="stage preflight failed; see errors") for item in data["images"]]
        report["counts"] = {status: sum(e["status"] == status for e in report["images"])
                            for status in ("rendered", "copied", "error", "not_processed")}
    atomic_write(output / "box_report.json", lambda temp: temp.write_text(json.dumps(report, indent=2) + "\n"))
    return report


def main():
    try:
        import yaml
        with open("config.yaml", encoding="utf-8") as stream:
            loaded = yaml.safe_load(stream)
        if not isinstance(loaded, dict):
            raise ValueError("config.yaml must contain a mapping")
        config = {**DEFAULTS, **loaded}
        config.update({key: os.environ[key] for key in config if key in os.environ})
        report = run(config)
        print(json.dumps(dict(complete=report["complete"], counts=report.get("counts", {}),
                              errors=report["errors"], image_errors=[
                                  {"source_file": item["source_file"], "error": item["error"]}
                                  for item in report.get("images", []) if "error" in item])))
        return 0 if report["complete"] else 1
    except Exception as error:
        print(f"Box stage failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

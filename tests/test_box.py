import importlib.util
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw
import pytest

spec = importlib.util.spec_from_file_location("mewc_box", Path(__file__).parents[1] / "src/mewc_box.py")
box = importlib.util.module_from_spec(spec)
spec.loader.exec_module(box)


def detection(category="1", conf=0.8):
    return dict(category=category, conf=conf, bbox=[0.1, 0.1, 0.5, 0.5])


def process(item, overlap, edge, minimum, upper, lower, policy):
    if item.get("failure") or item.get("detections") is None:
        raise ValueError("detector failure")
    return [d["conf"] >= float(lower) for d in item["detections"]]


def setup(root, images):
    for item in images:
        if "missing" not in item["file"]:
            path = root / item["file"]
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (24, 24), "olive").save(path)
    (root / "md_out.json").write_text(json.dumps({"images": images, "detection_categories": {"1": "animal", "2": "person", "3": "vehicle"}}))


def renderer(image, detections, threshold):
    assert len(detections) == 1
    ImageDraw.Draw(image).rectangle((1, 1, 12, 12), outline="red", width=3)


@pytest.mark.parametrize("value,expected", [(True, True), (False, False), ("True", True), ("False", False), (1, True), (0, False)])
def test_boolean_options(value, expected):
    assert box.parse_bool(value) is expected


@pytest.mark.parametrize("value", ["no", "falsehood", 2, None, []])
def test_invalid_boolean_fails(value):
    with pytest.raises(ValueError):
        box.parse_bool(value)


def test_false_options_copy_exact_nested_originals(tmp_path):
    images = [{"file": f"{site}/a.jpg", "detections": [detection()]} for site in ("one", "two")]
    setup(tmp_path, images)
    originals = {item["file"]: (tmp_path / item["file"]).read_bytes() for item in images}
    report = box.run({"INPUT_DIR": str(tmp_path), "DRAW": "False", "SUBFOLDER": "False"}, process,
                     lambda *_: pytest.fail("DRAW=false called renderer"))
    assert report["complete"], report
    for relative, content in originals.items():
        assert (tmp_path / relative).read_bytes() == content
        assert (tmp_path / "boxed" / relative).read_bytes() == content
    assert report["counts"]["copied"] == 2
    assert not (tmp_path / "boxed/animal").exists()


def test_last_ineligible_category_cannot_control_sort_and_missing_exif_renders(tmp_path):
    setup(tmp_path, [{"file": "site/a.jpg", "detections": [detection(), detection("2", 0.01)]}])
    original = (tmp_path / "site/a.jpg").read_bytes()
    report = box.run({"INPUT_DIR": str(tmp_path)}, process, renderer)
    assert report["complete"], report
    assert report["images"][0]["eligible_detection_indices"] == [0]
    assert (tmp_path / "boxed/animal/site/a.jpg").exists()
    assert (tmp_path / "site/a.jpg").read_bytes() == original
    assert (tmp_path / "boxed/animal/site/a.jpg").read_bytes() != original


def test_mixed_category_order_independent(tmp_path):
    setup(tmp_path, [{"file": "a.jpg", "detections": [detection(), detection("2")]},
                     {"file": "b.jpg", "detections": [detection("2"), detection()]}])
    report = box.run({"INPUT_DIR": str(tmp_path), "DRAW": False}, process)
    assert report["complete"]
    assert (tmp_path / "boxed/mixed/a.jpg").exists()
    assert (tmp_path / "boxed/mixed/b.jpg").exists()


def test_explicit_mixed_error_and_highest_confidence_tie(tmp_path):
    setup(tmp_path, [{"file": "a.jpg", "detections": [detection(), detection("2")]}])
    for policy in ("error", "highest_confidence"):
        report = box.run({"INPUT_DIR": str(tmp_path), "SORT_POLICY": policy}, process)
        assert not report["complete"]
        assert report["counts"]["error"] == 1


def test_blank_copy_and_failure_are_accounted(tmp_path):
    setup(tmp_path, [{"file": "site/blank.png", "detections": []},
                     {"file": "missing.jpg", "detections": [detection()]},
                     {"file": "fail.jpg", "detections": None, "failure": "decode"}])
    original = (tmp_path / "site/blank.png").read_bytes()
    report = box.run({"INPUT_DIR": str(tmp_path)}, process)
    assert not report["complete"]
    assert report["counts"] == {"rendered": 0, "copied": 1, "error": 2}
    assert (tmp_path / "boxed/blank/site/blank.png").read_bytes() == original
    assert json.loads((tmp_path / "boxed/box_report.json").read_text())["complete"] is False


def test_output_root_alias_rejected(tmp_path):
    (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="differ"):
        box.run({"INPUT_DIR": str(tmp_path), "OUTPUT_DIR": "alias"}, process)


def test_category_path_escape_is_per_image_failure(tmp_path):
    setup(tmp_path, [{"file": "a.jpg", "detections": [detection()]}])
    data = json.loads((tmp_path / "md_out.json").read_text())
    data["detection_categories"]["1"] = "../outside"
    (tmp_path / "md_out.json").write_text(json.dumps(data))
    report = box.run({"INPUT_DIR": str(tmp_path), "DRAW": False}, process)
    assert not report["complete"]
    assert "unsafe" in report["images"][0]["error"]


def test_cli_nonzero_on_image_failure(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("{}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "lib_common", None)
    monkeypatch.setattr(box, "run", lambda _: {"complete": False, "errors": []})
    assert box.main() == 1


def test_final_output_verification_failure_is_not_success(tmp_path, monkeypatch):
    setup(tmp_path, [{"file": "a.jpg", "detections": []}])
    original_hash = box.hashlib.sha256
    count = 0
    def fail_second_hash(value):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("injected final verification failure")
        return original_hash(value)
    monkeypatch.setattr(box.hashlib, "sha256", fail_second_hash)
    report = box.run({"INPUT_DIR": str(tmp_path), "DRAW": False}, process)
    assert not report["complete"]
    assert report["counts"]["error"] == 1


def test_shipped_config_matches_stage_defaults():
    import yaml
    shipped = yaml.safe_load(Path(box.__file__).with_name("config.yaml").read_text())
    assert shipped == box.DEFAULTS
    assert all(value is not None for value in shipped.values())


def test_main_shipped_config_renders_without_flow_lib_common(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    setup(tmp_path, [{"file": "site/a.jpg", "detections": [detection()]}])
    original = (tmp_path / "site/a.jpg").read_bytes()
    (tmp_path / "config.yaml").write_text(Path(box.__file__).with_name("config.yaml").read_text())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    monkeypatch.setitem(sys.modules, "lib_common", None)
    monkeypatch.setitem(sys.modules, "lib_tools", SimpleNamespace(process_detections=process))
    real_run = box.run
    monkeypatch.setattr(box, "run", lambda config: real_run(config, renderer=renderer))
    assert box.main() == 0
    assert json.loads(capsys.readouterr().out)["complete"] is True
    assert (tmp_path / "boxed/animal/site/a.jpg").read_bytes() != original
    assert (tmp_path / "site/a.jpg").read_bytes() == original
    report = json.loads((tmp_path / "boxed/box_report.json").read_text())
    assert report["complete"] is True
    assert report["draw"] is True


@pytest.mark.parametrize("document", ["", "- INPUT_DIR\n", "scalar\n"])
def test_main_rejects_nonmapping_yaml_before_processing(tmp_path, monkeypatch, capsys, document):
    (tmp_path / "config.yaml").write_text(document)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "lib_common", None)
    monkeypatch.setattr(box, "run", lambda _: pytest.fail("invalid YAML started processing"))
    assert box.main() == 1
    assert "config.yaml must contain a mapping" in capsys.readouterr().out

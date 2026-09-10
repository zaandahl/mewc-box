<img src="mewc_logo_hex.png" alt="MEWC Hex Sticker" width="200" align="right"/>

# mewc-box

The integrity changes in this checkout require the source builds described in [BUILDING.md](BUILDING.md). Published legacy tags do not provide these fixes. Use the tested image ID or digest from the generated image lock.

## Introduction
This repository contains code to build a Docker container for running mewc-box. This tool creates separate rendered or sorted copies, leaving source images unchanged, from camera trap images identified in  [MegaDetector](https://github.com/microsoft/CameraTraps/blob/main/megadetector.md) JSON output.

You can supply arguments via an environment file where the contents of that file are in the following format with one entry per line:
```
VARIABLE=VALUE
```

## Usage

After installing Docker you can run the container using a command similar to the following. Substitute `"$IN_DIR"` for your image directory and create a text file `"$ENV_FILE"` with any config options you wish to override. 

```
# Set STAGE_IMAGE to this stage's immutable image ID or registry digest from the generated image lock.
: "${STAGE_IMAGE:?Set the reviewed stage image}"
docker run --env-file "$ENV_FILE" \
    --interactive --tty --rm \
    --volume "$IN_DIR":/images \
    "$STAGE_IMAGE"
```

## Config Options

The following environment variables are supported for configuration (and their default values are shown). Simply omit any variables you don't need to change and if you want to just use all defaults you can leave `--env-file $ENV_FILE` out of the command alltogether. The last four options are designed to reduce a common effect where multiple spurious detection boxes are cascaded over a single animal in an effect similar to [Matryoshka](https://en.wikipedia.org/wiki/Matryoshka_doll) nesting dolls. 

| Variable | Default | Description |
| ---------|---------|------------ |
| INPUT_DIR | "/images/" | A mounted point containing images to process - must match the Docker command above |
| MD_FILE | "md_out.json" | MegaDetector output file, must be located in INPUT_DIR |
| OUTPUT_DIR | "boxed" | Separate derived-output tree under INPUT_DIR; never the input directory itself |
| DRAW | True | Draw eligible detection boxes; False makes byte-identical copies |
| SORT_POLICY | "mixed" | Mixed eligible categories go to MIXED_DIR; alternatives are error or highest_confidence |
| MIXED_DIR | "mixed" | Directory inside OUTPUT_DIR for images with multiple eligible detector categories |
| SUPPRESSION_POLICY | "category-confidence-v1" | Shared versioned eligibility; legacy-matryoshka-v1 remains an explicit historical option |
| SUBFOLDER | True | Sort derived copies into OUTPUT_DIR subfolders based on eligible detection categories |
| BLANK_DIR | "blank" | A subdirectory under OUTPUT_DIR for images with zero eligible detections |
| LOWER_CONF | 0.05 | The lowest detection confidence threshold to accept for snipping |
| OVERLAP | 0.3 | Matryoshka reduction - minimum proportional shared area for two boxes to be considered overlapping  |
| EDGE_DIST | 0.02 | Matryoshka reduction - minimum proportional edge distance for two boxes to share a 'close' edge |
| MIN_EDGES | 0 | Matryoshka reduction - minimum number of 'close' edges to consider removing smaller overlapped box |
| UPPER_CONF | 0.9 | Matryoshka reduction - upper detection confidence to give a 'free pass' for detection boxes|


## Output and sorting contract

`DRAW` and `SUBFOLDER` accept booleans or `True`/`False` and `1`/`0` strings (case insensitive). Other values fail. With both false, `site/image.jpg` is copied unchanged to `boxed/site/image.jpg`. Source files are never renamed or overwritten. Nested paths distinguish equal basenames at different sites. Unsafe paths, output/source overlap and symlink escapes are rejected.

Only detections retained by the configured shared suppression policy affect drawing or sorting. Zero eligible detections go to `BLANK_DIR`; one eligible category goes to its detector category folder; multiple eligible categories go to `MIXED_DIR` under the default `SORT_POLICY=mixed`. The last raw detection has no special role. `SORT_POLICY=error` refuses mixed categories. `SORT_POLICY=highest_confidence` chooses the category with highest eligible detection confidence, and refuses a cross-category confidence tie. These rules do not assert biological independence or animal abundance.

New runs use `category-confidence-v1`, which filters on the configured lower confidence, then applies higher-confidence-first suppression within each detector category with unchanged numeric overlap/edge/confidence thresholds. `legacy-matryoshka-v1` is an explicit historical alternative; it can be order-dependent and suppress across categories. Pass the same suppression policy and numeric thresholds to snipping, metadata and boxing. Historical outputs are not rewritten.

When `DRAW=False` or no detection is eligible, copies preserve exact bytes and modification time. Drawing supports images without EXIF and non-JPEG images supported by Pillow. Rendered images are derived, re-encoded visualisations; original bytes remain intact, and available EXIF/ICC metadata is carried into the rendering. Other embedded metadata is not guaranteed in rendered copies. Use the originals or Camelot export for metadata exchange.

`OUTPUT_DIR/box_report.json` records effective drawing/sorting/suppression policies, every image's retained original detection indices, source/output SHA-256, output path and status or error. Any image failure causes `complete=false` and a nonzero process exit. Source/configuration failures also exit nonzero. Output writes are atomic per file; use fresh output directories, and never treat partial outputs or stale files from an earlier run as a completed stage.

## Verification

Run `python -m pytest -q tests` with pytest and Pillow. Synthetic fixtures cover typed false options, duplicate nested basenames, missing EXIF, an ineligible last category, order-independent mixed sorting, blank copies, non-JPEG copies, source immutability, unsafe paths and per-image failure/nonzero exit accounting. Runtime drawing uses the detector's existing visualisation helper; tests inject a lightweight drawing function.

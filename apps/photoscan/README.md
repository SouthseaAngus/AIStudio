# Photoscan

Turns a folder of overlapping photos into a textured 3D model. It runs entirely on this Mac using Apple's Object Capture, with nothing uploaded.

## Build

```bash
./build.sh
```

## From Stream Deck

Press the Photoscan button and choose a folder of photos. A notification says it has started, and the model opens when it's done. It's saved as `Output/YYYY/MM/YYYY-MM-DD <folder> Scan/<folder>.usdz`. Only one scan runs at a time; pressing the button again while it's working just says so. If a run fails or is stopped, the log opens in Console.

To add the button, copy the Key Scenes key to an empty key, change its command to the Run command below, and set its icon to `apps/photoscan/button.png`.

| Stream Deck setting | Command |
|---|---|
| Run | `/Users/angus/AIStudio/apps/photoscan/start.sh` |
| Status (running / stopped) | `/Users/angus/AIStudio/apps/photoscan/status.sh` |
| Stop a run part-way | `/Users/angus/AIStudio/apps/photoscan/stop.sh` |

The button scans at `medium` detail. To use another level, set `PHOTOSCAN_DETAIL` (e.g. `PHOTOSCAN_DETAIL=full /Users/angus/AIStudio/apps/photoscan/start.sh`). Its output goes to `apps/photoscan/photoscan.log`.

## Use

Write one `.usdz` file, which opens in Quick Look and Preview:

```bash
./photoscan ~/Pictures/my-object ../../Output/scans/my-object.usdz
```

Or write a folder containing an OBJ with its material and textures, for use in other 3D software:

```bash
./photoscan ~/Pictures/my-object ../../Output/scans/my-object --detail full
```

| Option | What it does |
|---|---|
| `--detail <level>` | `preview`, `reduced`, `medium` (default), `full` or `raw`. Higher levels take longer and make bigger files. |
| `--sequential` | Use when photos are in the order they were taken, each overlapping the next. |
| `--high-sensitivity` | Finds more matching points on low-texture subjects, but is slower. |
| `--keep-background` | Keeps the surroundings instead of isolating the object. |

Start with `--detail preview` to check that a photo set works before running a higher level.

## Taking the photos

- Use a matte, textured subject that stays still. Shiny, transparent or plain surfaces scan poorly.
- Use soft, even light, and avoid hard shadows and flash.
- Take 40–100 sharp photos, or more for large or detailed subjects.
- Overlap neighbouring photos by about 70%.
- Circle the subject at low, middle and high angles.
- To capture the underside, turn the object over and photograph it again, keeping it in the same folder.
- Keep the subject large in the frame, and keep exposure and focal length consistent.

## Scale

Check dimensions against something you've measured before relying on them. Photos alone may not give true size, so a model may need scaling.

## Cleanup

The surroundings aren't always removed, even without `--keep-background`. A model can include the surface under the object and stray geometry around the edges, which you can trim in 3D software.

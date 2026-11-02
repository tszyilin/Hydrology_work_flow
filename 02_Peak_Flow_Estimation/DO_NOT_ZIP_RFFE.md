# Do not re-zip the RFFE plugin

**Do not run any zip / packaging step on `01_Rffe_plugin/`.**

## Why

`01_Rffe_plugin/` contains `NT_geology_outcrop_250K.shp` (+ sidecars), which is
~260 MB. Zipping the folder produces a `rffe_plugin.zip` of roughly the same
size, which is not what we want to distribute and clogs the working directory.

The RFFE plugin is only used locally / bundled inside the Peak Flow Toolbox
via `core/vendor/`, so a standalone RFFE zip is not needed.

## What to zip instead

Only `Peak_Flow_Toolbox/` should be packaged:

```
Peak_Flow_Toolbox.zip  <- the shippable artifact
```

Everything in `01_Rffe_plugin/` is source-of-truth for development; leave it
unpacked on disk.

## If a bad zip appears

Delete `rffe_plugin.zip` from the project root — it should not exist.

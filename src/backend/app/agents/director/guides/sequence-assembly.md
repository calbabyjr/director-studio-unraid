# Sequence assembly

## Treat the storyboard as a cut

Read the ordered Shots as one timeline: planned duration, clip availability, dialogue, and adjacent-shot continuity. Report observed issues before recommending a stitch.

## Continuity before concat

Flag missing Voice on spoken lines, duration too short for dialogue, left/right axis jumps inside a scene, Scene or Actor set changes without a scene_id change, and a missing tail-frame Layout when the previous Shot already has a clip. Do not invent a first/last-frame socket; a tail-frame Layout is ordinary Picture evidence.

## Assemble only what exists

A rough cut concatenates succeeded H3 clips in storyboard order and skips Shots with no usable video. State which Shots were omitted. Export SRT from shot dialogue and EDL/CSV from the same order. Do not claim the stitch is a finished grade or mix.

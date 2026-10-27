# Spinnaker reference tests

Three ways of showing FLUX what the Spinnaker Tower looks like, run directly
against ComfyUI on the Mac Studio. Put this folder at ~/AIStudio/reference-tests
and run from ~/AIStudio with the venv active:

    cd ~/AIStudio && source .venv/bin/activate
    python reference-tests/reference_tests.py --help

photos/ holds harbour.jpg (side-on, from the harbour), closeup.jpg (from the
quayside) and skyline.jpg (from across the water). Results go to
~/AIStudio/Output/YYYY/MM/YYYY-MM-DD Reference Tests/ with tests.jsonl recording
every setting.

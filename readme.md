
# Bag => Hdl21 Schematic Porting 

WIP scripting to port BAG schematic-YAML and generators to Hdl21. 

## Usage

If you can run 
```
python -c "import bag"
```
... you've already done the hard part. 

* Go to a working BAG workspace
* Enable it, "source" it, whatever you do to make it run BAG programs
* Come back here
* `source .bashrc_pypath`
  * Note this depends on environment variables set in prior steps 
* Test: `python -c "import bag"`
  * If that fails, (shrug emoji)

BAG inherited nearly all of the dumbest decisions from the EDA software that preceded it. 
Such as *not* packaging insanely difficult-to-build C and C++ libraries, 
but instead insisting on bringing its own Python interpreter. 

So to run stuff with "BAG Python", you may need to invoke it directly, e.g. 
```
$BAG_PYTHON -m pip install pydantic
```
or 
```
$BAG_PYTHON export.py
```


# Bag => Hdl21 Schematic Porting 

WIP scripting to port BAG schematic-YAML and generators to Hdl21.  
This is **highly informal** and intended to be used in ad-hoc, grad-student-grade modes. 


## Usage

### Porting Schematic YAML

Porting a schematic-YAML file to Python code can be performed through the simple CLI `run.py`: 

```
python run.py port examples/inv_tristate.yaml
```

Should produce output along the lines of: 

```python
@h.generator
def inv_tristate(params: Params) -> h.Module:
    m = h.Module()

    m.add(h.Inout(), name="VDD")
    # ...

    i = m.add(nmos4_stack(h.Default)(), name="XN")
    i.connect("d", m.get("out"))
    # ...

    return m
```

For more elaborate use cases, dig around the package, particularly `code.py`, 
grab whichever stuff looks like it does what you want. 


### The BAG Part

Ideally `Hdl21BagPorting` will ultimately be able to comprehend the *python* part of 
BAG's schematic generators as well. This requires some version of running them (or even worse, parsing them). 

Sadly BAG inherited nearly all of the dumbest decisions from the EDA software that preceded it. 
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

If you can run 
```
python -c "import bag"
```
... you've already done the hard part. 

All of the facets of this work which import BAG are work-in-progress.  
If you want to work on them, and trial-and-error generated means: 

* Go to a working BAG workspace
* Enable it, "source" it, whatever you do to make it run BAG programs
* Come back here
* `source .bashrc_pypath`
  * Note this depends on environment variables set in prior steps 
* Test: `python -c "import bag"`
  * If that fails, (shrug emoji)


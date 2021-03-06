# pywasm3-doom-demo
WebAssembly (WASI) [DOOM demo](https://twitter.com/wasm3_engine/status/1393588527863144450)

## Run
```sh
pip3 install -r pip-requirements.txt
python3 wasm3-doom.py
```

## Features

- [x] `WASI` layer implementation
- [x] Virtual file system
- [x] Indexed color buffer display using `PyGame` and `NumPy`
- [ ] Keyboard input
- [ ] Mouse input
- [ ] Audio

## Licenses and sources

[DOOM Open Source Release](https://github.com/id-Software/DOOM) is used to produce `wasidoom.wasm`.

The Doom 1 shareware WAD file is (C) Copyright id Software.
The DOOM shareware wad is freely distributable.

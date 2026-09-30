# Third-party notices

Samvaad's own code is released under the Apache License 2.0 (see `LICENSE`). It builds on the following work.

## Code

### Qualcomm AI Hub Apps: Whisper Windows sample

`samvaad/engines/asr_qnn.py` adapts the Whisper decode loop and the ONNX Runtime QNN session setup from Qualcomm's `whisper_windows_py` sample app (https://github.com/quic/ai-hub-apps).

```
Copyright 2025 Qualcomm Technologies, Inc. and/or its subsidiaries.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## Models (downloaded by `setup.ps1` or `setup.sh`, not stored in this repository)

| Model | Used for | Source | Licence |
| --- | --- | --- | --- |
| Whisper-Base (encoder and decoder, precompiled for the Hexagon NPU) | Speech recognition | Qualcomm AI Hub, fetched with `qai-hub-apps` | Source model: Apache-2.0 (Hugging Face `openai/whisper-base`); deployable export: Qualcomm AI Hub Models licence |
| Whisper tokenizer, config and feature extractor | Speech recognition | Hugging Face `openai/whisper-base` | Apache-2.0 |
| Qwen3-4B-Instruct-2507 | Translation, plain words, Recall, summaries | Qualcomm AI Hub via GenieX | Apache-2.0; Qualcomm Generative AI usage terms apply to the AI Hub build |
| Whisper-small (or the size you choose), CTranslate2 format | Speech recognition on laptops without a Snapdragon NPU | Hugging Face `Systran/faster-whisper-small`, converted from `openai/whisper-small` | MIT |
| Qwen3-4B-Instruct-2507, 4-bit GGUF (`qwen3:4b-instruct-2507-q4_K_M`) | Translation on laptops without a Snapdragon NPU | Ollama library | Apache-2.0 |

## Runtime components

ONNX Runtime and onnxruntime-qnn (MIT), Hugging Face Transformers (Apache-2.0), faster-whisper (MIT), CTranslate2 (MIT), NumPy (BSD-3-Clause), Starlette (BSD-3-Clause), Uvicorn (BSD-3-Clause), HTTPX (BSD-3-Clause), wsproto (MIT). GenieX is Qualcomm software installed separately under Qualcomm's terms. Ollama (MIT) and uv (MIT or Apache-2.0) are installed separately by the setup scripts when needed.

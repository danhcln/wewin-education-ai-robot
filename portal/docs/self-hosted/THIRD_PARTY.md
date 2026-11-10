# Source and model license record

The seven surveyed repositories remain separate checkouts under
`E:/WeWIN_Firmware_Lab/references/xiaozhi`; their code was inspected, not installed
as an entire stack or copied wholesale into the Portal. See the implementation
report for pinned SHAs and concrete source paths. GitHub stars were not a
selection criterion. Dependency/model licenses are separate from repository MIT.

- xinnan-tech server, joey-zhou Java server, hackers365 Go server, 78 firmware,
  huangjunsen0406 client, 78 assets generator: root MIT notices at surveyed SHAs.
  Retain copyright/permission notices for any distributed reused source.
- ESP-SR: **ESPRESSIF MIT**, permission scoped to Espressif products. Prebuilt
  libraries/models do not mean all implementation source is available. Used for
  offline research only, not as a general host speech engine.
- `opuslib_next` bindings and libopus: independent codec/binding licenses;
  Windows staging uses x64 DLL from the pinned py-xiaozhi reference checkout.
  Native version reports `libopus unknown`; reference SHA and binary hash can pin
  this staging input, but native build provenance/version is not established.
  Provision/audit a known libopus build before product distribution. Linux image
  uses system libopus package. No DLL was embedded in the new source bundle.
- faster-whisper: MIT engine; [converted Whisper base weights](https://huggingface.co/Systran/faster-whisper-base)
  record MIT. Download pins revision `ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66`.
- [Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B): Apache-2.0 model card. Local
  Ollama model/digest is recorded in runtime evidence; no model/template replaced.
- Education staging comparison also used [Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B)
  and [Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct), both
  Apache-2.0 per primary model cards. They were pulled only into the isolated E:
  evaluation store/11435, not the shared 11434 model store. Runtime was stopped
  after evaluation; no production model promotion. Actual GGUF digests in receipts.
- Tokenizers are pinned public artifacts, not downloaded by inference code:
  Qwen3-4B revision `1cfa9a7208912126459214e8b04321603b3df60c`, Qwen2.5-7B
  revision `a09a35458c702b33eeacc393d103063234e8bc28`. Local receipt includes SHA-256
  for tokenizer.json/config; all data remains ignored under data/ai-*.
- Supertonic SDK/sample code: MIT; **Supertonic 3 model: BigScience Open RAIL-M**,
  not MIT. [Model license](https://huggingface.co/Supertone/supertonic-3/blob/main/LICENSE)
  has use/distribution restrictions and notices, including hosted-service scope.
  Provision model LICENSE/card with the weights and review intended product use;
  no blanket commercial clearance is asserted by this source survey.
- WebRTC VAD wrapper/library, PyAV/FFmpeg, ONNX Runtime, CTranslate2 and all pip
  dependencies retain their own notices/build conditions. The installed Windows
  dependency lock is an inventory, not a claim that all components are MIT.
- ESP-SR models, fonts/GIFs/emojis and py-xiaozhi GUI dependencies were not copied
  into the WeWIN product. Font/media/dependency rights need separate review if
  later reused; a top-level repository license is not a grant for arbitrary art.

WeWIN's own canonical `knowledge_policy.py` is loaded read-only from the existing
Connector source. The prepared Docker context contains WeWIN source, no keys,
model weights, database or firmware backup; no upload/deployment was performed.

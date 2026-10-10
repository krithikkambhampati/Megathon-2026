"""Convert already-trained artefacts to the committed compressed form (one-off / idempotent).

models/**/model*.txt -> model*.txt.gz (manifest model_files updated);
outputs/test_predictions/*.csv -> .csv.gz.
New training runs already write the compressed form (training/common.py save_model).
"""

from __future__ import annotations

import gzip
import json
import shutil

from training.common import MODELS, PRED


def main() -> None:
    for man_path in sorted(MODELS.rglob("manifest.json")):
        d = man_path.parent
        man = json.loads(man_path.read_text())
        files = []
        for f in man["model_files"]:
            src = d / f
            if f.endswith(".txt") and src.exists():
                with src.open("rb") as fi, gzip.open(d / f"{f}.gz", "wb", compresslevel=9) as fo:
                    shutil.copyfileobj(fi, fo)
                src.unlink()
                f = f"{f}.gz"
            files.append(f)
        man["model_files"] = files
        man_path.write_text(json.dumps(man, indent=2))
        print(f"{d.relative_to(MODELS)}: {files[0]}{' ...' if len(files) > 1 else ''}")
    for csv in sorted(PRED.glob("*.csv")):
        with csv.open("rb") as fi, gzip.open(PRED / f"{csv.name}.gz", "wb", compresslevel=9) as fo:
            shutil.copyfileobj(fi, fo)
        csv.unlink()
        print(f"{csv.name} -> {csv.name}.gz")


if __name__ == "__main__":
    main()

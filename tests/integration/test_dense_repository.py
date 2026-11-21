import re
import shutil

import numpy as np

from techsearch import dense
from techsearch.repository import CORPUS_FILES, Documents, Passages


class FixtureTokenizer:
    def __call__(self, text, **kwargs):
        offsets = [(match.start(), match.end()) for match in re.finditer(r"\S+", text)]
        return {"offset_mapping": offsets, "input_ids": list(range(len(offsets)))}


class FixtureEncoder:
    tokenizer = FixtureTokenizer()

    def get_sentence_embedding_dimension(self):
        return 3

    def encode(self, texts, **_options):
        return np.tile(np.array([0, 0, 1], dtype=np.float32), (len(texts), 1))


def test_dense_storage_alignment_and_cache(tmp_path, settings, release, monkeypatch):
    stage = tmp_path / "dense-fixture"
    stage.mkdir()
    for filename in CORPUS_FILES:
        shutil.copyfile(release.path / filename, stage / filename)
    monkeypatch.setattr(dense, "load_encoder", lambda *_args, **_options: FixtureEncoder())
    settings.dense.update(chunk_tokens=9, overlap_tokens=2)
    info = dense.build_dense(stage, settings, {"repo": "fixture", "revision": "0" * 40, "files": {}})
    assert info["passages"] > len(Documents(stage).parents)
    repo = Passages(stage)
    repo.validate(Documents(stage))
    assert tuple(repo.vectors[0]) == (0, 0, 1)
    with repo.reader() as read:
        assert read(0)["parent"] == int(repo.parents[0])
    assert len(list(dense.model_path(settings).glob("embeddings/*/*/*.npy"))) > 0

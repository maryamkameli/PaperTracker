from papertracker.library import Library, Owned
from papertracker.models import Paper


def test_library_round_trip(tmp_path):
    lib = Library(tmp_path / "library.csv")
    p = Paper(title="Vection, Revisited", arxiv_id="2611.00001v3", authors=["A B"], published="2026-11-15", topic="sickness", score=0.8123)
    lib.add(p, "2026-11-16")
    lib.save()
    again = Library(tmp_path / "library.csv")
    assert len(again) == 1
    assert Paper(title="something else", arxiv_id="2611.00001") in again
    assert Paper(title="VECTION revisited!") in again
    assert again.rows["arxiv:2611.00001"]["score"] == "0.812"


def test_owned_reads_titles_and_arxiv_ids(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "GaussianAvatars- Photorealistic Head Avatars with Rigged 3D Gaussians.pdf").write_bytes(b"%PDF")
    (tmp_path / "sub" / "2003.08934.pdf").write_bytes(b"%PDF")
    owned = Owned([str(tmp_path), str(tmp_path / "missing")])
    assert Paper(title="GaussianAvatars: Photorealistic Head Avatars with Rigged 3D Gaussians") in owned
    assert Paper(title="NeRF", arxiv_id="2003.08934v2") in owned
    assert Paper(title="Something new") not in owned
    assert owned.names == ["GaussianAvatars- Photorealistic Head Avatars with Rigged 3D Gaussians"]

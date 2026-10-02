from card3d.cli import main


def test_skill_installs(tmp_path):
    assert main(["skill", "--dir", str(tmp_path)]) == 0
    text = (tmp_path / "3d-card" / "SKILL.md").read_text()
    assert text.startswith("---\nname: 3d-card\n")

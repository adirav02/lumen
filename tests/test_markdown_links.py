"""Active local links, URL fragments and code examples."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'development/scripts'))
from check_docs import check_links


def test_targets_and_anchors(tmp_path):
    (tmp_path/'sub').mkdir()
    (tmp_path/'sub'/'target.md').write_text('# A title\n# A title\n')
    entry=tmp_path/'README.md'
    entry.write_text('[ok](sub/target.md#a-title-1) [web](https://example.com/x)\n```md\n[example](missing.md)\n```\n`[inline](missing.md)`\n')
    assert check_links(tmp_path,['README.md'])==[]
    entry.write_text('[bad](sub/target.md#absent) [bad](missing.md)')
    errors=check_links(tmp_path,['README.md'])
    assert len(errors)==2

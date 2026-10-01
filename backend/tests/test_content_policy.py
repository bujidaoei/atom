import pytest

from app.content_policy import ContentPolicyError,is_control_path,validate_content_manifest
from app.snapshots import Entry,VerifiedSnapshot


@pytest.mark.parametrize('path',['_atom','_atom/access/index.html','_ATOM/access','_Atom/file'])
def test_reserved_root_file_or_directory_rejects_entire_manifest(path):
    manifest=VerifiedSnapshot('a'*64,(Entry('index.html',1,'b'*64),Entry(path,1,'c'*64)))
    with pytest.raises(ContentPolicyError,match='reserved_content_path'):validate_content_manifest(manifest)


@pytest.mark.parametrize('path',['_atomic/page','nested/_atom/page','atom/page','%5fatom/page','index.html'])
def test_unrelated_project_paths_remain_valid(path):
    validate_content_manifest(VerifiedSnapshot('a'*64,(Entry(path,1,'b'*64),)))


@pytest.mark.parametrize('path',['/_atom','/_atom/access','/_ATOM/access','//_atom/missing'])
def test_control_requests_cannot_use_spa_fallback(path):
    assert is_control_path(path)

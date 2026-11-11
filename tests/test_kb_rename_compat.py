"""Values stored under the old zn names before 2.0.2 still work after the rename to kb."""

import hashlib
import os

from backend import passwords


def test_a_password_wrapped_under_the_old_name_still_signs_in():
    digest = hashlib.sha256(b"family-Pass-1").hexdigest()
    new = passwords.wrap_unsalted_sha256(digest)
    assert new.startswith("$kb-sha256-argon2id$")
    old = passwords.WRAPPED_SHA256_BEFORE + new[len(passwords.WRAPPED_SHA256) :]
    assert old.startswith("$" + "zn-sha256-argon2id$")
    assert passwords.verify_password("family-Pass-1", old) and passwords.verify_password("family-Pass-1", new)
    assert not passwords.verify_password("wrong", old)
    assert passwords.needs_rehash(old)  # the next sign-in stores it as Argon2id


def test_an_old_import_staging_folder_is_tidied(tmp_path):
    from backend.services import photo_import

    for name in (".kb-import", "." + "zn-import"):
        os.makedirs(tmp_path / name)
        (tmp_path / name / "x.part").write_text("half")
    job = photo_import.Importer.__new__(photo_import.Importer)
    job.destination = str(tmp_path)
    job.tidy()
    assert not (tmp_path / ".kb-import").exists() and not (tmp_path / ("." + "zn-import")).exists()

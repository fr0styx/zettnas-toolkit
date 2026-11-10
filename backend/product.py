"""The product's names, in one place (the Kiboto rebrand; the old ones are in legacy_names)."""

NAME = "Kiboto"
AI_NAME = "Kib"
SLUG = "kiboto"
IMAGE_REPO = "fr0styx/kiboto"  # ghcr.io/<this>
GITHUB_REPO = "fr0styx/kiboto"
CONTAINER = "kiboto"  # Kiboto's own container on a new install
IMAGE = "ghcr.io/" + IMAGE_REPO
HOST_APPDATA = "/mnt/user/appdata/kiboto"  # Unraid's appdata folder on a new install
MANAGED_LABEL = "com.kiboto.managed"  # on what Kiboto installs: it stops only its own apps on a power cut
APP_LABEL = "com.kiboto.app"  # on an app's own network (NSEC-10)
FOLLOW_TAG_LABEL = "kiboto.image.follow-tag"  # a pinned image whose updates follow its tag

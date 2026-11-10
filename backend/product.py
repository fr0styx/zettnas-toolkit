"""The product's names, in one place (the Kiboto rebrand; the old ones are in legacy_names)."""

NAME = "Kiboto"
AI_NAME = "Kib"
SLUG = "kiboto"
IMAGE_REPO = "fr0styx/kiboto"  # ghcr.io/<this>
GITHUB_REPO = "fr0styx/kiboto"
MANAGED_LABEL = "com.kiboto.managed"  # on what Kiboto installs: it stops only its own apps on a power cut
APP_LABEL = "com.kiboto.app"  # on an app's own network (NSEC-10)
FOLLOW_TAG_LABEL = "kiboto.image.follow-tag"  # a pinned image whose updates follow its tag

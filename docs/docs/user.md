---
subtitle: User command line reference manual
layout: main
---

## SYNOPSIS

For a quick start introduction, please look [here](quick.md).

```
aliBuild build [-h] [--defaults DEFAULT]
               [-a ARCH] [--force-unknown-architecture]
               [-z [DEVELPREFIX]] [-e ENVIRONMENT] [-j JOBS] [-u]
               [--no-local PKGLIST] [--force-tracked] [--disable PACKAGE]
               [--force-rebuild PACKAGE] [--annotate PACKAGE=COMMENT]
               [--only-deps] [--plugin PLUGIN]
               [--always-prefer-system | --no-system]
               [--docker] [--docker-image IMAGE] [--docker-extra-args ARGLIST] [-v VOLUMES]
               [--no-remote-store] [--remote-store STORE] [--write-store STORE] [--insecure]
               [--ac-store STORE] [--legacy-links-store STORE] [--cas-public-url URL]
               [--storage {ephemeral,permanent}] [--no-snapshot-sources]
               [--sign-url URL] [--sign-token TOKEN] [--sign-token-file FILE]
               [--signer NAME] [--no-sign]
               [--require-signature {off,warn,require}] [--trusted-keys KEYRING]
               [--plan]
               [-C DIR] [-w WORKDIR] [-c CONFIGDIR] [--reference-sources MIRRORDIR]
               [--aggressive-cleanup] [--no-auto-cleanup]
               PACKAGE [PACKAGE ...]
```

- `PACKAGE`: One of the packages in `CONFIGDIR`. May be specified multiple
  times.
- `-h`, `--help`: show this help message and exit
- `--defaults DEFAULT`: Use defaults from `CONFIGDIR/defaults-DEFAULT.sh`.
- `-a ARCH`, `--architecture ARCH`: Build as if on the specified architecture.
  When used with `--docker`, build inside a Docker image for the specified
  architecture. Default is the current system architecture.
- `--force-unknown-architecture`: Build on this system, even if it doesn't have
  a supported architecture.
- `-z [DEVELPREFIX]`, `--devel-prefix [DEVELPREFIX]`: Version name to use for
  development packages. Defaults to branch name.
- `-e ENVIRONMENT`: KEY=VALUE binding to add to the build environment. May be
  specified multiple times.
- `-j JOBS`, `--jobs JOBS`: The number of parallel compilation processes to run.
- `-u`, `--fetch-repos`: Fetch updates to repositories in `MIRRORDIR`. Required
  but nonexistent repositories are always cloned, even if this option is not
  given.
- `--no-local PKGLIST`: Do not pick up the following packages from a local
  checkout. `PKGLIST` is a comma-separated list.
- `--force-tracked`: Do not pick up any packages from a local checkout.
- `--disable PACKAGE`: Do not build `PACKAGE` and all its (unique) dependencies.
- `--force-rebuild PACKAGE`: Always rebuild the specified packages from scratch,
  even if they were built before. Has the same effect as adding
  `force_rebuild: true` to the recipe. May be specified multiple times or
  separate multiple arguments with commas.
- `--annotate PACKAGE=COMMENT`: Store `COMMENT` in the build metadata for
  `PACKAGE`. The comment will only be stored if the package is compiled or
  downloaded during this run. May be specified multiple times.
- `--only-deps`: Only build dependencies, not the main package. Useful for
  populating a build cache.
- `--plan`: Resolve the build and print what it *would* do -- for each
  package the version-revision it lands on, its hash, and whether it comes
  from the remote store or gets built -- then stop. Unlike `-n`/`--dry-run`,
  which returns before any of that is known, this runs the real resolution
  and therefore reads the remote store. Its `reuse` lines are
  `PACKAGE/VERSION-REVISION` specs, which is the form
  [`aliBuild migrate`](#migrating-legacy-tarballs) consumes.
- `--plugin PLUGIN`: Plugin to use for the build. Default is `legacy`.
- `--always-prefer-system`: Always use system packages when compatible.
- `--no-system`: Never use system packages, even if compatible.

### Building inside a container

Builds can be done inside a Docker container, to make it easier to get a common,
usable environment. The Docker daemon must be installed and running on your
system. By default, images from `alisw/<platform>-builder:latest` will be used,
e.g. `alisw/slc8-builder:latest`. They will be fetched if unavailable.

- `--docker`: Build inside a Docker container.
- `--docker-image IMAGE`: The Docker image to build inside of. Implies
  `--docker`. By default, an image is chosen based on the architecture.
- `--docker-extra-args ARGLIST`: Command-line arguments to pass to `docker run`.
  Passed through verbatim -- separate multiple arguments with spaces, and make
  sure quoting is correct! Implies `--docker`.
- `-v VOLUMES`: Additional volume to be mounted inside the Docker container, if
  one is used. May be specified multiple times. Passed verbatim to `docker run`.

### Re-using prebuilt tarballs

Reusing prebuilt tarballs saves compilation time, as common packages need not be
rebuilt from scratch. `rsync://`, `https://`, `b3://`, `s3://`, `reapi://`
and `cvmfs://` remote stores are recognised. Some of these require
credentials: `s3://` remotes require an `~/.s3cfg`; `b3://` and `reapi://`
remotes require `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment
variables, and for `reapi://` that applies to reading as well as writing. A useful remote store is
`https://s3.cern.ch/swift/v1/alibuild-repo`. It requires no credentials and
provides tarballs for the most common supported architectures. See
[Reusing builds from CVMFS](#reusing-builds-from-cvmfs-experimental) for the `cvmfs://`
store, which reuses packages already deployed on CVMFS without downloading
anything.

- `--no-remote-store`: Disable the use of the remote store, even if it is
  enabled by default.
- `--remote-store STORE`: Where to find prebuilt tarballs to reuse. See above
  for available remote stores. End with `::rw` if you want to upload (in that
  case, `::rw` is stripped and `--write-store` is set to the same value).
  Implies `--no-system`. May be set to a default store on some architectures;
  use `--no-remote-store` to disable it in that case.
- `--write-store STORE`: Where to upload newly built packages. Same syntax as
  `--remote-store`, except `::rw` is not recognised. Implies `--no-system`.
- `--insecure`: Don't validate TLS certificates when connecting to an `https://`
  remote store. For a `reapi://` store it selects `http` for the endpoint
  instead, which is what a local MinIO or a loopback credential broker needs.

The options below apply only to `reapi://` stores. See
[Content-addressed stores and the Action
Cache](#content-addressed-stores-and-the-action-cache) for what they are for.

- `--ac-store STORE`: A separate ledger store for the Action Cache and the
  reconstruction inputs (recipe, source, refs), which are kept even though
  the artifact tarballs are deletable. Same `::rw` syntax as
  `--remote-store`. Defaults to `--remote-store`.
- `--legacy-links-store STORE`: Where to publish the legacy `TARS/<arch>/`
  link and store objects, if not in the artifact store. Use this to keep an
  existing repository browsable by consumers that only understand that
  layout, while the bytes stay content-addressed.
- `--cas-public-url URL`: Public base URL of the CAS bucket, e.g.
  `https://s3.cern.ch/swift/v1/alibuild-cas`. Required with
  `--legacy-links-store`, because the legacy store objects redirect there by
  absolute URL, and the endpoint a build uploads *through* -- a credential
  broker, say -- is not necessarily the one consumers read from.
- `--storage {ephemeral,permanent}`: Retention for uploaded tarball blobs.
  `ephemeral` (the default) lets the bucket lifecycle expire them;
  `permanent` pins them, and also promotes any ephemeral blob the build
  reuses. Use `permanent` for production builds.
- `--no-snapshot-sources`: Don't archive built packages' git sources into the
  ledger. Source archival is best-effort and is skipped for partial
  (blobless or treeless) mirrors anyway; with this flag
  `aliBuild reconstruct` falls back to fetching sources from upstream git.
- `--sign-url URL`: Endpoint of the signing route used to sign Action Cache
  entries, e.g. `https://<proxy>/sign/alibuild-ac`. Uploading to a `reapi://`
  store signs by default and requires this unless `--no-sign` is given.
- `--sign-token TOKEN`: Credential presented to `--sign-url`. Prefer
  `--sign-token-file` for short-lived credentials.
- `--sign-token-file FILE`: Read the credential for `--sign-url` from `FILE`,
  freshly for every signing request. Use this for a token that is refreshed
  in place while the build runs -- a workload-identity JWT whose lifetime is
  minutes, against a build that signs entries for hours.
- `--signer NAME`: Human-readable signer label recorded in the signature. The
  key id is what is actually checked. Default `alibuild`.
- `--no-sign`: Upload to a `reapi://` store without signing Action Cache
  entries.
- `--require-signature {off,warn,require}`: How to treat signatures on
  prebuilt `reapi://` tarballs reused during the build: `warn` (the default;
  log unverified entries and carry on), `off` (don't check), or `require`
  (fail closed).
- `--trusted-keys KEYRING`: Path to a JSON keyring of trusted signing keys.
  This **replaces** the defaults, which are the keyring shipped inside
  aliBuild merged with `keyring.json` from the alidist checkout, if there is
  one.

### Customise aliBuild directories

- `-C DIR`, `--chdir DIR`: Change to the specified directory before building.
  Alternatively, set `ALIBUILD_CHDIR`. Default `.`.
- `-w WORKDIR`, `--work-dir WORKDIR` The toplevel directory under which builds
  should be done and build results should be installed. Default `sw`.
- `-c CONFIGDIR`, `--config-dir CONFIGDIR`: The directory containing build
  recipes. Default `alidist`.
- `--reference-sources MIRRORDIR`: The directory where reference git
  repositories will be cloned. `%(workDir)s` will be substituted by `WORKDIR`.
  Default `%(workDir)s/MIRROR`.

### Cleaning up after building

- `--aggressive-cleanup`: Delete as much build data as possible when cleaning
  up.
- `--no-auto-cleanup`: Do not clean up build directories automatically after a
  build.

## Using precompiled packages

By running aliBuild with no special option on CentOS/Alma 7, 8 or 9 (x86-64 or ARM),
or on Ubuntu 20.04, 22.04 or 24.04 (x86-64), it will automatically try to
use as many precompiled packages as possible by downloading them from a default
central server. By using precompiled packages you lose the ability to pick some
of them from your system. If you do not want to use precompiled packages and you
want to pick as many packages as possible from your system, you should manually
specify the `--always-prefer-system` option.

It is possible to benefit from precompiled builds on every platform, provided
that the server caching the builds is maintained by yourself. Since every build
is stored as a tarball with a unique hash, it is sufficient to provide for a
server or shared space where cached builds will be stored and made available to
others.

In order to specify the cache store, use the option `--remote-store <uri>`,
where `<uri>` can be:

* a local path, for instance `/opt/alibuild_cache`,
* a remote SSH accessible path, `ssh://<host>:<path>`,
* an unencrypted rsync path, `rsync://<host>/path`,
* a CERN S3 bucket, `b3://<bucket>`,
* a HTTP(s) server, `http://<host>/<path>`,
* a CVMFS deployment, `cvmfs://<path>` (read-only, see below).

The first four options can also be writable (if you have proper permissions):
if you specify `::rw` at the end of the URL, your builds will be cached there.
This is normally what sysadmins do to precache builds: other users can simply
use the same URL in read-only mode (no `::rw` specified) to fetch the builds.

You need to make sure you have proper filesystem/SSH/rsync permissions of
course.

It is also possible to specify a write store different from the read one by
using the `--write-store` option.

aliBuild can reuse precompiled packages if they were built with a different tag,
if that tag points to the same actual commit that you're building now. (This is
used for the nightly tags, as they are built from a branch named
`rc/nightly-YYYYMMDD`, while alidist is updated to have a tag like
`nightly-YYYYMMDD` instead, pointing to the same commit.) However, this reuse
only works if the precompiled package has the same version as specified in your
copy of alidist.

This approach assumes that tags don't move (i.e. don't change which commit they
are tagging) in the repositories being built. If you administer a cache store,
make sure to delete cached tarballs built using that tag if a tag is moved!

### Reusing builds from CVMFS (experimental)

If the packages you need are already deployed on [CVMFS](https://cernvm.cern.ch/fs/)
(for instance under `/cvmfs/alice.cern.ch`), aliBuild can reuse them directly,
without downloading or repacking any tarball. Instead of copying data, it
creates symlinks pointing into the CVMFS tree, so reuse is essentially
instantaneous and takes no extra disk space.

To enable this, point `--remote-store` at the CVMFS path using the `cvmfs://`
prefix:

```bash
aliBuild build O2 --remote-store cvmfs:///cvmfs/alice.cern.ch
```

Note the triple slash: `cvmfs://` is the scheme and `/cvmfs/alice.cern.ch` is
the absolute filesystem path to the deployment. aliBuild looks for packages
under `<path>/<architecture>/Packages/<package>/<version>`, mapping
architectures such as `slc8_x86-64` to their CVMFS equivalent (`el8-x86_64`)
automatically.

A few things to keep in mind:

* The CVMFS store is **read-only**: it cannot be used as a write store, and
  appending `::rw` or passing it to `--write-store` is not supported. Packages
  that are not found on CVMFS are simply rebuilt locally as usual.
* As with any remote store, a build is reused only if its hash (or an
  equivalent remote hash) matches what your copy of alidist would produce, so
  keep alidist in sync with the version deployed on CVMFS.

## Content-addressed stores and the Action Cache

A `reapi://` store keeps the same tarballs as the stores above, but addresses
them by the hash of their *contents* rather than by the hash of the build that
produced them, and it records how each one was built. The layout is modelled on
the [Remote Execution API](https://github.com/bazelbuild/remote-apis) and, inside
the bucket, looks like this:

* `cas/<algo>/<xx>/<hash>` -- the content-addressed blobs: tarballs, archived
  recipes, archived sources. Digests are `sha256`. Two builds whose difference
  never reaches the output -- two tags on the same commit, say -- deduplicate to
  a single blob.
* `ac/<arch>/<xx>/<hash>.json` -- one *Action Cache* entry per build, keyed by
  the same action hash the classic store uses to name its files. It records the
  recipe, the source commit, the action hashes of the dependencies, the build
  environment, and the `outputDigest` of the tarball that came out.
* `TARS/<arch>/...` -- the classic store object, symlink and `.manifest` tree is
  still written, with the store object as an S3 redirect to the CAS blob. Plain
  `https://` clients and the CVMFS and RPM publishers therefore keep working,
  and no bytes are stored twice.

Recording the Action Cache buys two things the classic store cannot do. A
package can be installed straight from the store with no recipes at all, because
its entry already lists its runtime closure -- see
[`aliBuild install`](#installing-a-prebuilt-package). And a tarball that has been
deleted can be rebuilt from the entry that described it -- see
[`aliBuild reconstruct`](#reconstructing-a-missing-tarball). That is what makes
the tarballs safe to delete: the ledger is small and kept forever, while the
artifacts are large and regenerable.

### Addressing a reapi:// store

The URL is `reapi://<endpoint-host>/<bucket>`, and both halves are optional:

```bash
# The standard CERN layout: endpoint s3.cern.ch, blobs in alibuild-cas, the
# ledger in alibuild-ac, legacy links in alibuild-repo.
aliBuild build O2 --remote-store reapi://

# One named bucket, which opts out of the three-bucket default: the ledger and
# the legacy links then live in that same bucket.
aliBuild build O2 --remote-store reapi://s3.cern.ch/my-cache::rw
```

Naming a bucket opts out of the split entirely, so a single-bucket store stays a
single bucket. Credentials come from `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY`, for reading as well as for writing.

### Retention

Tarball blobs are tagged `retention=ephemeral` on upload unless
`--storage permanent` is given. Ephemeral blobs are expired by the bucket
lifecycle rule 90 days after they were last written or last reused; permanent
ones are kept indefinitely. Ledger objects -- Action Cache entries, archived
recipes and archived sources -- are never tagged and never expire, which is what
makes it useful to keep them in their own bucket with `--ac-store`: the artifact
store can then be emptied without losing the ability to rebuild it.

### Signing

Action Cache entries can carry Ed25519 signatures, so that a consumer can tell
that an entry -- and, through its `outputDigest`, the bytes it points at -- came
from a build it trusts rather than from whoever happened to be able to write to
the bucket.

Uploads to a `reapi://` store are signed **by default**, and are refused unless
either `--sign-url` (with `--sign-token` or `--sign-token-file`) or `--no-sign`
is given. aliBuild never holds the private key: it sends the bytes to be signed
to the endpoint named by `--sign-url`, which signs them and returns the
signature.

On the consuming side -- `build` reusing a prebuilt tarball, `install`,
`reconstruct` -- `--require-signature` selects the policy and defaults to
`warn`. The keyring is the one shipped inside aliBuild
(`alibuild_helpers/keyring.json`), merged with `keyring.json` from the alidist
checkout when there is one; `--trusted-keys` replaces both. Merging can add keys
but never widens trust: validity windows intersect and revocations are unioned,
so a key revoked in the shipped keyring stays revoked whatever another keyring
says about it. Verification needs the optional `cryptography` dependency
(`pip install alibuild[signing]`); without it, `warn` degrades to a warning and
`require` fails.

### Installing a prebuilt package

`aliBuild install` installs a package and its runtime closure straight from a
`reapi://` store. It needs no alidist and runs no build: the Action Cache entry
already names the closure, and the relocation logic ships inside the tarball, so
neither has to be resolved or reimplemented.

```bash
aliBuild install GenTopo --version nightly-20261015 \
    --remote-store reapi:// --prefix /opt/alisw
```

- `PACKAGE`: the package to install.
- `--version VERSION`: required.
- `--revision REVISION`: defaults to the highest available for the version.
- `--prefix DIR`: where to install. Defaults to the work directory.

It also takes `--remote-store` (required here, unlike for `build`), `--ac-store`,
`--insecure`, `-a`/`--architecture`, `-w`/`--work-dir`, `--require-signature` and
`--trusted-keys`, all as described above.

Each package is unpacked into `<prefix>/<arch>/<package>/<version>-<revision>`
and its in-tarball `relocate-me.sh` is run against the prefix; the package's own
`etc/profile.d/init.sh` then sets up the environment. A package already present
at that path is left alone, so re-running the command is cheap.

### Reconstructing a missing tarball

`aliBuild reconstruct` walks the *build* closure of a package in the Action
Cache, finds the tarballs missing from the CAS, and materialises the archived
recipes into a self-contained alidist directory. An ordinary
`aliBuild build ... --remote-store reapi://...::rw` against that directory then
recomputes the same action hashes, rebuilds what is missing and repopulates the
CAS.

```bash
# What would it take, and is the ledger actually complete?
aliBuild reconstruct O2 --version nightly-20261015 \
    --remote-store reapi:// --verify

# Prove the recorded blob can be regenerated byte for byte.
aliBuild reconstruct O2 --version nightly-20261015 \
    --remote-store reapi:// --verify --rebuild
```

- `--verify`: read-only. Reports the plan -- which tarballs would be reused from
  the CAS and which rebuilt -- and checks the ledger for recipe integrity, a
  complete dependency DAG and archived sources. Rebuilds nothing.
- `--rebuild`: with `--verify`, actually rebuild just the target package,
  reusing every dependency from the CAS and uploading nothing, then compare the
  resulting tarball's content hash against the recorded `outputDigest`. A match
  proves the blob is byte-for-byte regenerable.
- `--strict`: with `--verify --rebuild`, treat a non-identical rebuild as a
  failure. The default is lenient, because tarballs produced before output
  normalisation are not bit-reproducible.
- `--persist`: rebuild the target and, if it reproduces the recorded digest,
  upload just that one blob back -- a content-addressed restore. Unlike a
  `build ... ::rw` it writes nothing else: no revision assignment, no publisher
  symlinks, no Action Cache rewrite, because all of those already point at the
  blob. A dry run unless `--apply` is given.
- `--rebaseline`: rebuild the target and, where its reproducible hash differs
  from the recorded (legacy) one, rewrite the entry's `outputDigest` and the
  store redirect to the rebuilt hash, so later verifications are byte-identical.
  A dry run unless `--apply`; `--delete-old` additionally removes the blob the
  re-baseline orphans.
- `--output-config DIR`: where to materialise the recipes. Defaults to
  `WORKDIR/reconstruct-PACKAGE`.
- `--alidist DIR`: an alidist checkout to take the defaults file
  (`defaults-<name>.sh`) from. A defaults file is configuration rather than a
  package in the closure, so it is not archived in the ledger; this is needed to
  rebuild a release built with non-`release` defaults, such as `o2`.
- `--storage {ephemeral,permanent}`: retention for a blob restored by
  `--persist`. Defaults to `permanent`, on the grounds that a deliberately
  reconstructed blob should not then be LRU-expired.

### Migrating legacy tarballs

`aliBuild migrate` turns tarballs from a classic store into reapi entries, so
that releases built before any of this existed become installable and
reconstructible. For each tarball it reads the embedded `.meta.json` provenance,
recovers the full recipe from the alidist commit recorded there, synthesises the
Action Cache entry, and writes the CAS blob, the recipe blob, the entry, the
legacy redirect and the per-package link. The old store is only ever read, never
written.

```bash
# Preview a whole architecture, closures included, writing nothing.
aliBuild migrate --match '.*' --closure -n -a slc9_x86-64 \
    --read-store https://s3.cern.ch/swift/v1/alibuild-repo \
    --alidist ~/alidist --remote-store reapi://

# Migrate one release and everything it was built from, for keeps.
aliBuild migrate O2PDPSuite/nightly-20261015-1 --closure -j 8 \
    --read-store https://s3.cern.ch/swift/v1/alibuild-repo \
    --alidist ~/alidist --remote-store reapi://::rw --storage permanent
```

- `TARBALL...`: local paths, or `PACKAGE/VERSION-REVISION` specs when
  `--read-store` is given. `aliBuild build --plan` prints specs in that form.
- `--read-store URL`: read-only `http(s)` old store to fetch tarballs from.
- `--alidist DIR`: alidist checkout or mirror from which to recover recipes at
  the recorded commits. Required to migrate tarballs.
- `--closure`: treat each argument as a top package and migrate its whole build
  closure, read from the old store's `dist` tree. Requires `--read-store`.
- `--match REGEX`: migrate every `PACKAGE/VERSION-REVISION` published for the
  architecture in the old store whose spec matches (Python `re.search`); `.*`
  takes the whole architecture. Composes with `--closure` and with
  `-n`/`--dry-run`.
- `-j JOBS`, `--jobs JOBS`: migrate this many packages in parallel, overlapping
  the downloads and uploads. Peak disk use scales with it.
- `--snapshot-sources`: also archive each release's git source into the ledger,
  so the release can be reconstructed with neither its tarball nor its upstream
  still around. Idempotent: an already-migrated release is enriched in place
  from its Action Cache entry, with no tarball re-download and no CAS rewrite.
  Given no `TARBALL`, it walks the whole ledger instead, which works even after
  the old store has pruned the tarballs.
- `--source-mirror DIR`: where to cache the source clones `--snapshot-sources`
  makes. Defaults to `WORKDIR/MIRROR-migrate`.
- `--allow-no-provenance`: for tarballs predating `.meta.json`, store the
  tarball, its redirect and its link anyway, reserving the version-revision so
  that a later fresh build cannot shadow it. Such packages are preserved and
  installable but **not** reconstructible, since no ledger entry can be
  recovered for them.
- `--container IMAGE`: container image to record for the migrated builds, marked
  as assumed rather than observed. Defaults to the architecture's default
  builder.
- `--no-verify`: skip the structural self-check of recovered recipes -- that
  each one parses, that its package field matches the metadata, and that every
  recorded dependency carries a hash. Entries failing the check are skipped
  rather than written.
- `--populate-system`: walk the whole ledger and add `validate-system` nodes to
  every build entry, to backfill entries migrated before that became automatic.
  Idempotent, and honours `-n`/`--dry-run`.

Two limitations are worth knowing before planning a bulk migration. Archived
sources are git-only, so Sapling-backed packages are skipped. And
self-verification is structural: it does not yet recompute the action hash and
match it against the store key.

## Developing packages locally

One of the use cases we want to cover is the ability to develop external
packages without having to go through an commit - push - pull cycle.

In order to do so, you can simply checkout the package you want to
develop at the same level as alibuild and alidist.

For example, if you want to build O2 while having the ability to modify
ROOT, you can do the following:

    git clone https://github.com/alisw/alidist
    git clone https://github.com/root-mirror/root ROOT
    <modify files in ROOT/>
    aliBuild ... build O2

The above will make sure the build will pick up your changes in the local
directory.

As a cherry on the cake, in case your recipe does not require any environment,
you can even do:

    cd sw/BUILD/ROOT/latest
    make install

and it will correctly install everything in `sw/<arch>/ROOT/latest`.
This of course mean that for each development package you might end up
with one or more build directories which might increase the used disk
space.

It's also important to notice that if you use your own checkout of a
package, you will not be able to write to any store and the generated
tgz will be empty.

If you wish to temporary compile with the package as specified by
alidist, you can use the `--no-local <PACKAGE>` option.

### Incremental builds

When developing locally using the development mode, if the external
is well behaved and supports incremental building, it is possible to
specify an `incremental_recipe` in the YAML preamble. Such a recipe will
be used after the second time the build happens (to ensure that the non
incremental parts of the build are done) and will be executed directly
in $BUILDDIR, only recompiled what changed. Notice that if this is the
case the incremental recipe will always be executed.

### Forcing a different architecture

While alibuild does its best to find out which OS / distribution you are
using, sometimes it might fail to do so, for example in the case you
start using a new *buntu flavour or a bleeding edge version of a distribution.
In order to force the correct architecture for the build you can use
the `--architecture` (`-a`) flag with one of the supported options:

On Linux, x86-64:
- `slc6_x86-64`: RHEL6 / SLC6 compatible
- `slc7_x86-64`: RHEL7 / CC7 compatible
- `slc8_x86-64`: RHEL8 / CC8 compatible
- `slc9_x86-64`: RHEL9 / ALMA9 compatible
- `slc10_x86-64`: RHEL10 / ALMA10 compatible
- `ubuntu2004_x86-64`: Ubuntu 20.04 compatible
- `ubuntu2204_x86-64`: Ubuntu 22.04 compatible
- `ubuntu2404_x86-64`: Ubuntu 24.04 compatible
- `fedora33_x86-64`: Fedora 33 compatible
- `fedora34_x86-64`: Fedora 34 compatible

On Linux, ARM:
- `slc9_aarch64`: RHEL9 / ALMA9 compatible

On Linux, POWER8 / PPC64 (little endian):
- `slc7_ppc64`: RHEL7 / CC7 compatible

On Mac:
- `osx_x86-64`: Intel
- `osx_arm64`: Apple Silicon

### Running in Docker

Very often one needs to run on a platform which is different from
the one being used for development. The common use case is that
development happens on a Mac while production runs on some older Linux
distribution like SLC5 or SLC6. In order to improve the experience
of cross platform development aliBuild now offers the ability to run
in [Docker](https://docker.io) via the `--docker` option. When it is
specified the first part of the architecture will be used to construct
the name of the docker container to be used for the build and the build
itself will be performed inside that container. For example if you
specify:

```bash
alibuild --docker -a slc7_x86-64 build ROOT
```

the build itself will happen inside the alisw/slc7-builder Docker
container. Environment variables can be passed to docker by specifying
them with the `-e` option. Extra volumes can be specified with the -v
option using the same syntax used by Docker.

## Defaults

By default, `aliBuild` uses the `o2` defaults (`--defaults o2`), which are
optimized for building the ALICE O2 software stack. The defaults system
allows you to specify different sets of build configurations, compiler
flags, and package versions through the `--defaults` option.

Different defaults can be used to:
- Use different package versions (e.g., different ROOT versions)
- Apply specific compiler flags (e.g., debug builds, optimization levels)
- Enable or disable certain features or packages

To use a different set of defaults, use the `--defaults <name>` option,
which will load settings from `CONFIGDIR/defaults-<name>.sh`. For example,
`--defaults o2-epn` would use the `defaults-o2-epn.sh` file.

For a more complete description of how the defaults system works and how to
create custom defaults, please look at [the reference manual](reference.md#defaults).

## Disabling packages

You can optionally disable certain packages by specifying them as a comma
separated list with the `--disable` option.

It's also possible to disable packages by adding them to the `disable` keyword
of your defaults file (see previous paragraph). See the
[defaults-o2.sh](https://github.com/alisw/alidist/blob/master/defaults-o2.sh)
file for an example of how to disable `mesos` and `MySQL` when
passing `--defaults o2`.

## Controlling which system packages are picked up

When compiling, there is a number of packages which can be picked up
from the system, and only if they are not found, do not have their
devel part installed, or they are not considered good enough they are
recompiled from scratch. A typical example is things like autotools,
zlib or cmake which should be available on a standard developer machine
and we rebuild them as last resort. In certain cases, to ensure full
compatibility on what is done in production it might be desirable to
always pick up our own version of the tools. This can be done by passing
the `--no-system` option to alibuild. On the other hand, there might
be cases in which you want to pick up not only basic tools, but also
advanced ones like ROOT, Geant4, or Pythia from the system, either to
save time or because you have a pre-existing setup which you do not want
to touch. In this case you can use `--always-prefer-system` option which
will try very hard to reuse as many system packages as possible (always
checking they are actually compatible with the one used in the recipe).

## Cleaning up the build area (new in 1.1.0)

Whenever you build using a different recipe or set of sources, alibuild
makes sure that all the dependent packages which might be affected
by the change are rebuild, and it does so in a different directory.
This can lead to the profiliferation of many build / installation
directories, in particular while developing a recipe for a new package
(e.g. a new generator).

In order to remove all past builds and only keep the latest one for each
alidist area you might have used and for each breanch (but not commit)
ever build for a given development package you can use the

    aliBuild clean

subcommand which will do its best to clean up your build and
installation area.

## Upgrading aliBuild

aliBuild can be installed either via `pip`, or by your OS package manager (more info [here](https://alice-doc.github.io/alice-analysis-tutorial/building/custom.html). 

The way to upgrade it depends on your installation method. If you installed it
via `pip`, you can upgrade it by running:

    pip install --upgrade alibuild

In general updating aliBuild is safe and it should never trigger a rebuild or
break compilation of older versions of alidist (i.e. we do try to guarantee
backward compatibility). In no case an update of aliBuild will result in the
update of `alidist`, which users will have to be done separately.
In case some yet to appear bug in alibuild will force us to rebuild a
previously built area, this will be widely publicized and users will get a warning
when running the command.

You can also upgrade / install a specific version of alibuild by specifying it on the 
command line. E.g.:

    pip install alibuild=1.17.23
    

## Rebuilding packages from branches instead of tags

Generally, recipes specify a Git _tag_ name in the `tag:` field. In some cases,
_branch names_ might be used instead (such as `tag: master` or `tag: dev`). In
such a rare case, aliBuild needs to know what is the last branch commit to
determine whether a rebuild is necessary.

Such check by default uses cached information instead of doing very slow queries
to remote servers. This means that aliBuild is fast in determining which
packages to build. However, packages using branch names might not get rebuilt as
expected when new changes are pushed to those branches.

In this case, you can ask aliBuild to update cached branches information by
adding the `-u` or `--fetch-repos` option. Note that by default this is not
needed, it's only for very special use cases (such as centralized builds and
server-side pull request checks).

## Generating a dependency graph

It is possible to generating a PDF with a dependency graph using the `aliBuild deps`
tool. Assuming you run it from a directory containing `alidist`, and you have
Graphviz installed on your system, you can simply run:

    aliBuild deps O2 | dot -Tpdf -o graph.pdf

The example above generates a dependency graph for the package `O2`, and saving
the results to a PDF file named `graph.pdf`. This is what the graph looks like:

![drawing](deps.png)

Packages in green are runtime dependencies, purple are build dependencies, while
red packages are runtime dependencies in some cases, and build dependencies in
others (this can indicate an error in the recipes).

Connections are color-coded as well: blue connections indicate a runtime
dependency whereas a grey connection indicate a build dependency.

By default, `aliBuild deps` runs the usual system checks to exclude packages that can
be taken from the system. If you want to display the full list of dependencies,
you may want to use:

    aliBuild deps O2 --no-system | dot -Tpdf -o graph.pdf

As usual you can customise the input of dot using `tred` to produce a graph with 
a transitive reduction:

    aliBuild deps O2 --no-system | tred | dot -Tpdf -o graph.pdf

Please run `aliBuild deps --help` for further information.

## Using the packages you have built

### Loading the package environment

Environment for packages built using aliBuild is managed by
[Environment Modules](http://modules.sourceforge.net) and the wrapper script
`alienv`. To list the available packages you can do:

    alienv q

while:

    alienv enter VO_ALICE@PackageA::VersionA[,VO_ALICE@PackageB::VersionB...]

will enter a shell with the appropriate environment set. Note that loading a
toplevel package recursively sets the environment for all its dependencies.

You can also execute a command with the proper environment without altering the
current one. For instance:

    alienv setenv VO_ALICE@AliRoot::latest -c aliroot -b

To see other commands consult the online manual:

    alienv help

Environment Modules is required: the package is usually called
`environment-modules` on Linux, or simply `modules` if using Homebrew on OSX.

Note that `alienv` works exactly like the one found on CVMFS, but for local
packages built with `aliBuild`.

### Environment for packages lacking a module definition

Some packages do not have a modulefile: this usually occurs for those which are
not distributed on the Grid. If you think this is wrong feel free to submit a
[pull request](https://github.com/alisw/alidist/pulls) or
[open an issue](https://github.com/alisw/alidist/issues) to the relevant
packages.

It is still possible to load the environment by sourcing the `init.sh` file
produced for each package under the `etc/profile.d` subdirectory. For instance:

    WORK_DIR=$PWD/sw source sw/slc7_x86-64/AliRoot/v5-08-02-1/etc/profile.d/init.sh

Dependencies are automatically loaded.

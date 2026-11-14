Name:           alibuild
Version:        %{?version}%{!?version:0}
Release:        1%{?dist}
Summary:        ALICE Build Tool
License:        GPL-3.0-or-later
URL:            https://github.com/alisw/alibuild
Source0:        alibuild-%{version}-py3-none-any.whl

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3-pip

Requires:       python3
Requires:       git
Requires:       python3-pyyaml
Requires:       python3-requests
Requires:       python3-distro

%description
ALICE Build Tool for building HEP software.

%prep
%build

%install
%{python3} -m pip install --root %{buildroot} --prefix %{_prefix} --no-deps --no-index %{SOURCE0}

%files
%{python3_sitelib}/alibuild_helpers/
%{python3_sitelib}/alibuild-*.dist-info/
%{_bindir}/aliBuild
%{_bindir}/alienv
%{_bindir}/aliDoctor
%{_bindir}/aliDeps
%{_bindir}/pb

%changelog
* Tue Jan 14 2025 ALICE Offline <alice-offline@cern.ch>
- See https://github.com/alisw/alibuild/releases for release notes

Name:           python-alibuild
Version:        %{?version}%{!?version:0}
Release:        1%{?dist}
Summary:        ALICE Build Tool
License:        GPL-3.0-or-later
URL:            https://github.com/alisw/alibuild
Source0:        alibuild-%{version}-py3-none-any.whl

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3-pip

%global _description %{expand:
ALICE Build Tool for building HEP software.}

%description %_description

%package -n python3-alibuild
Summary:        %{summary}

%description -n python3-alibuild %_description

%prep
%build

%install
%{python3} -m pip install --root %{buildroot} --prefix %{_prefix} --no-deps --no-index %{SOURCE0}

%files -n python3-alibuild
%{python3_sitelib}/alibuild_helpers/
%{python3_sitelib}/alibuild-*.dist-info/
%{_bindir}/aliBuild
%{_bindir}/alienv
%{_bindir}/aliDoctor
%{_bindir}/aliDeps
%{_bindir}/pb

%changelog

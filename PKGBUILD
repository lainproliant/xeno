pkgbase='python-xeno'
pkgname=('python-xeno')
_module='xeno'
pkgver='4.0.4'
pkgrel=1
pkgdesc="The Python dependency injector from outer space."
url="https://github.com/lainproliant/xeno"
depends=('python')
makedepends=('python-setuptools')
license=('BSD')
arch=('any')
source=("https://files.pythonhosted.org/packages/source/${_module::1}/$_module/$_module-$pkgver.tar.gz")
sha256sums=('bef63b2f6a95b765324156684c09c6a31ed9c3f63496005155433c67eecc0cdd')

build() {
    cd "${srcdir}/${_module}-${pkgver}"
    python setup.py clean --all
    python setup.py build
}

package() {
    depends+=()
    cd "${srcdir}/${_module}-${pkgver}"
    python setup.py install --root="${pkgdir}" --optimize=1 --skip-build
    install -Dm644 "$srcdir/${_module}-${pkgver}/LICENSE" "${pkgdir}/usr/share/licenses/${pkgname}/LICENSE"
}

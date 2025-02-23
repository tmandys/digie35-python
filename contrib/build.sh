#!/bin/env bash


MAKE_LIBGPHOTO2=
# Debian package is not the same as original, requires original DEBIAN/* stuff
MAKE_LIBGPHOTO2_DIST=1
MAKE_PYTHON_GPHOTO2=1

SAVE_DIR=$(cd `dirname $0`; pwd)
LIBGPHOTO2_DIR=$SAVE_DIR/libgphoto2
CONFIGURE_PARAMS="--prefix=$HOME/.local --enable-static"

red_color='\033[0;31m'
yellow_color='\033[1;33m'
no_color='\033[0m'

function get_libgphoto2_version() {
    # looking for "        [2.5.31.2],"
    VERSION=$(sed -n "s/^.*\[\(2\.5\.[0-9]\+\.[0-9]\+\)\],/\1/p" $LIBGPHOTO2_DIR/configure.ac)
    if [ ! $VERSION ] ; then
        echo "Cannot get version from configure.ac"
        exit 1
    fi
    echo "libgphoto2 version: $VERSION"
}

if [ $MAKE_LIBGPHOTO2 ] ; then

    echo -e "${yellow_color}Building libgphoto2${no_color}"

    # cannot use a dash delimited suffix as python-gphoto2 will complain. So increase last digit
    get_libgphoto2_version

    echo "Enter new version, unless already patched then recommended is rightmost digit increase by one or confirm [$VERSION]"
    read new_version
    if [ $new_version ] ; then
        if [ $new_version != $VERSION ] ; then
            echo "Patching $VERSION -> $new_version"
            sed -e "s/\[\(2\.5\.[0-9]\+\.[0-9]\+\)\]/[$new_version]/" -i $LIBGPHOTO2_DIR/configure.ac
        fi
    else
        echo "Leaving $VERSION"
    fi
    patch -u -N -p 1 -d $LIBGPHOTO2_DIR -i $SAVE_DIR/libgphoto2.diff

    cd $LIBGPHOTO2_DIR

    autoreconf -is
    ./configure $CONFIGURE_PARAMS
    make

	cd $SAVE_DIR
fi

if [ $MAKE_LIBGPHOTO2_DIST ] ; then

    cd $LIBGPHOTO2_DIR
	echo "Building packages"
	make dist

    get_libgphoto2_version

	debmake -a $LIBGPHOTO2_DIR/libgphoto2-$VERSION.tar.gz
	cd libgphoto2-$VERSION
	sed -i 's/\(libgphoto2 ([0-9]*\.[0-9]*\.[0-9]*\.[0-9]*-[0-9]*\))/\1~digie35)/' debian/changelog
    PKG_VERSION=$(sed -n 's/.*(\([^)]\).*/\1/p' debian/changelog)
	echo "Package version: $PKG_VERSION"
	echo "override_dh_auto_configure:" >> /debian/rules
	echo "	./configure $CONFIGURE_PARAMS" >> /debian/rules
	debuild
    cd $SAVE_DIR
	PKG_FILEPATH=libgphoto2_${PKG_VERSION}_arm64.deb

	mv "libgphoto2_${PKG_VERSION}*" $LIBGPHOTO2_DIR

	rpi_project_dir=../../digie35-rpi
	repo_dir="$rpi_project_dir/apt-repo"
	package_dir="$repo_dir/pool/main"

	echo "Copying Debian package to repository"
	cp ${LIBGPHOTO2_DIR}/${PKG_FILEPATH} ${package_dir}
	${rpi_project_dir}/build_repo.sh

	#sudo dpkg --install --prefix=$HOME/.local $LIBGPHOTO2_DIR/${PKG_FILEPATH}
fi

if [ $MAKE_PYTHON_GPHOTO2 ] ; then
    echo -e "${yellow_color}Building python-gphoto2${no_color}"
    TGT_DIR=python-gphoto2

    get_libgphoto2_version

    libgphoto2_prefix=`PKG_CONFIG_PATH=$LIBGPHOTO2_DIR pkg-config --variable=libdir libgphoto2`
    echo "libgphoto2 libdir: ${libgphoto2_prefix}"
    # build_swig get finally installed library, not library in build libgphoto2 directory
    INSTALLED_VERSION=`PKG_CONFIG_PATH=$libgphoto2_prefix/pkgconfig pkg-config --modversion libgphoto2`
    if [ $INSTALLED_VERSION != $VERSION ] ; then
        echo "libgphoto2 library [$VERSION] in not installed, installed is [$INSTALLED_VERSION]"
        echo "Run 'cd libgphoto2; make install' ? [y]"
        read yesno
        if [ "xx$yesno" == "xx" ] ; then
            yesno=y
        fi
        if [ $yesno == "y" ] ; then
            cd $LIBGPHOTO2_DIR
            make install
        else
            echo -e "${red_color}Using currently installed libgphoto2 library [$INSTALLED_VERSION]. It might be not intended!${no_color}"
        fi
    fi

    cd $SAVE_DIR/$TGT_DIR
    patch -u -N -p 1 -d . -i $SAVE_DIR/python-gphoto2.diff

    #version in pyproject.toml dynamically from README.rst via swig
    # python-gphoto2 v\ 2.5.1
    sed -e "s/^\(python-gphoto2 [^0-9]*\)\(.*\)/\1$VERSION/" -i README.rst

    #LIBGPHOTO2_DIR=/home/pi/.local
    echo "Running SWIG"
    python3 developer/build_swig.py $LIBGPHOTO2_DIR

    echo "Pip install: $LIBGPHOTO2_DIR"
    GPHOTO2_ROOT=$LIBGPHOTO2_DIR pip install --user . -vvvv --debug

    echo "Building wheel"
    GPHOTO2_ROOT=$LIBGPHOTO2_DIR python3 setup.py bdist_wheel

    cd $SAVE_DIR

    REMOTE="html/repos/digie35/python/"
    echo "To upload run command:"
    CMD="lftp -c \"open ftp://2pcz@ftp.web4u.cz; mirror -R $TGT_DIR/dist/ $REMOTE \""
    echo $CMD
	echo "Run it now ? [n]"
    read yesno
    if [ "xx$yesno" == "xxy" ] ; then
        eval $CMD
    fi

fi

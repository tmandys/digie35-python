#!/bin/env bash


MAKE_LIBGPHOTO2=1
MAKE_PYTHON_GPHOTO2=1
# Debian package is not the same as original, requires original DEBIAN/* stuff
MAKE_LIBGPHOTO2_DIST=

SAVE_DIR=$(cd `dirname $0`; pwd)
LIBGPHOTO2_DIR=$SAVE_DIR/libgphoto2

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

    echo "Building libgphoto2"

    # cannot use a dash delimited suffix as python-gphoto2 will complain. So increase last digit

    TGT_DIR=$SAVE_DIR/libgphoto2

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
    ./configure --prefix=$HOME/.local
    make

    if [ $MAKE_LIBGPHOTO2_DIST ] ; then
        echo "Building packages"
        make dist-tgz

        debmake -a libgphoto2-$VERSION.tar.gz
        cd libgphoto2-$VERSION
        debuild
    fi

    cd $SAVE_DIR
fi

if [ $MAKE_PYTHON_GPHOTO2 ] ; then
    echo "Building python-gphoto2"
    TGT_DIR=python-gphoto2

    get_libgphoto2_version
    
    cd $SAVE_DIR/$TGT_DIR
    patch -u -N -p 1 -d . -i $SAVE_DIR/python-gphoto2.diff

    #version in pyproject.toml dynamically from README.rst via swig
    # python-gphoto2 v\ 2.5.1
    sed -e "s/^\(python-gphoto2 [^0-9]*\)\(.*\)/\1$VERSION/" -i README.rst

    LIBGPHOTO2=$SAVE_DIR/libgphoto2
    #LIBGPHOTO2=/home/pi/.local
    echo "Running SWIG"
    python3 developer/build_swig.py $LIBGPHOTO2

    echo "Pip install: $LIBGPHOTO2"
    GPHOTO2_ROOT=$LIBGPHOTO2 pip install --user . -vvvv --debug

    echo "Building wheel"
    GPHOTO2_ROOT=$LIBGPHOTO2 python3 setup.py bdist_wheel

    cd $SAVE_DIR

    REMOTE="html/drupal/repos/python/"
    echo "To upload run command:"
    CMD="lftp -c \"open ftp://2pcz@ftp.web4u.cz; mirror -R $TGT_DIR/dist/ $REMOTE \""
    echo $CMD
    # eval $CMD

fi
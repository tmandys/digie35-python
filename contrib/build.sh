!/bin/env sh

DIR=`dirname $0`

echo "Building libgphoto2"

cd $DIR/libgphoto2

# from configure.ac
VERSION=2.5.31.2
make dist-tgz

debmake -a libgphoto2-$VERSION.tar.gz
cd libgphoto2-$VERSION
debuild

echo "Building  python-gphoto2"
cd $DIR/python-gphoto2

#version in pyproject.toml

LIBGPHOTO2=$DIR/libgphoto2
#LIBGPHOTO2=/home/pi/.local
echo "Running SWIG"
python3 developer/build_swig.py $LIBGPHOTO2

echo "Pip install: $LIBGPHOTO2"
GPHOTO2_ROOT=$LIBGPHOTO2 pip install --user . -vvvv --debug

echo "Building wheel"
GPHOTO2_ROOT=$LIBGPHOTO2 python3 setup.py bdist_wheel

REMOTE="html/drupal/repos/python/"
CMD="lftp -c \"open ftp://2pcz@ftp.web4u.cz; mirror -R dist/ $REMOTE \""
echo $CMD
eval $CMD

cd $DIR
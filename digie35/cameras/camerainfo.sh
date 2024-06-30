#!/bin/bash

GPHOTO2=gphoto2
MODEL=`$GPHOTO2 --summary |grep Model:|cut -d " " -f 2`
if [ -z $MODEL ]
then
	echo "No camera found"
	exit 1
fi
FILENAME="$MODEL.info"
echo Writing $FILENAME

DELIM="################################################################################"
function get_data() {
	CMD="$GPHOTO2 $1"
	echo $CMD
	echo $DELIM >> $FILENAME
	echo "### $CMD ###" >> $FILENAME
	echo $DELIM >> $FILENAME
	echo >> $FILENAME
	$GPHOTO2 $1 >> $FILENAME
	echo >> $FILENAME
}

LC_ALL=C
export LC_ALL

date > $FILENAME
echo >> $FILENAME

get_data "--summary"
get_data "--abilities"
get_data "--list-config"
get_data "--list-all-config"




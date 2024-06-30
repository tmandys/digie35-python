#!/bin/sh

watch -d -n 0.1 "\
  echo -n 'Front:   '; raspi-gpio get 5;\
  echo -n 'Rear:    '; raspi-gpio get 6;\
  echo -n 'Middle:  '; raspi-gpio get 7;\
  echo -n 'Adapter: '; raspi-gpio get 8;\
  "

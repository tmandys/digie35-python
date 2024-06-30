Scan_stat Overview
==================

Scan root directory for pattern files and builds statistics by creation date and file owner. The data are propagated
to HTML template to visualize using Google Charts API. The CSV data are injected into local file based on template.
The charts are rendered locally on client machine, no data are sent outside.

For pattern specification see https://facelessuser.github.io/wcmatch/glob/. Path are relative to root dir.

---- RRD data

The most recent data are available in hourly interval, less recent data in daily, weekly and monthly interval. The data format is CSV. The time is in hours.

Example:

hourly data:
2023-06-12 19:00;pi;22
2023-06-12 20:00;pi;82
2023-06-12 21:00;pi;50
2023-06-13 15:00;pi;83
2023-06-13 16:00;pi;159
2023-06-14 23:00;pi;37
2023-06-15 13:00;pi;151
2023-06-17 19:00;pi;30
2023-06-17 21:00;pi;86
2023-06-17 22:00;pi;182
2023-06-17 23:00;pi;168
2023-06-18 12:00;pi;39
2023-06-18 13:00;pi;249
2023-06-18 14:00;pi;76
2023-06-18 15:00;pi;213
2023-06-18 16:00;pi;217
2023-06-18 17:00;pi;39
2023-07-13 21:00;pi;152

daily data:
2023-06-12;pi;154
2023-06-13;pi;242
2023-06-14;pi;37
2023-06-15;pi;151
2023-06-17;pi;466
2023-06-18;pi;833
2023-07-13;pi;152

weekly data:
2023-W24;pi;1883
2023-W28;pi;152

monthly data:
2023-06;pi;1883
2023-07;pi;152

Requirements
------------

python 3.8+ (i.e. version supported still on Windows 7), wcmatch module (install with pip)


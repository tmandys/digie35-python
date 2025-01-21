#!/usr/bin/env python3

from lxml import etree

namespaces = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "tiff": "http://ns.adobe.com/tiff/1.0/",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
}

preset_xml = '''
    <x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 5.6-c128 79.159124, 2016/03/18-14:01:55">
        <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
            <rdf:Description
                rdf:about=""
                xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
                xmlns:tiff="http://ns.adobe.com/tiff/1.0/"
                xmlns:dc="http://purl.org/dc/elements/1.1/"
                crs:Saturation="-100"
                crs:ToneCurveName="Custom"
                tiff:Orientation="PRESET ATTR"
                dc:Identifier="PRESET ATTR"
            >
                <crs:ToneCurve>
                    <rdf:Seq>
                    <rdf:li>0, 255</rdf:li>
                    <rdf:li>255, 0</rdf:li>
                    </rdf:Seq>
                </crs:ToneCurve>
                <tiff:Orientation>PRESET ELEM[0]</tiff:Orientation>
                <tiff:Orientation>PRESET ELEM[1]</tiff:Orientation>
                <tiff:Orientation>PRESET ELEM[2]</tiff:Orientation>
                <dc:Identifier>PRESET ELEM ěščř</dc:Identifier>
            </rdf:Description>
        </rdf:RDF>
    </x:xmpmeta>
'''

custom_xml = '''
    <x:xmpmeta xmlns:x="adobe:ns:meta/">
        <rdf:RDF
            xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
            >
            <rdf:Description 
                xmlns:xmp="http://ns.adobe.com/xap/1.0/"
                xmlns:dc="http://purl.org/dc/elements/1.1/"
                xmlns:tiff="http://ns.adobe.com/tiff/1.0/"
                xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"
                rdf:about="_MG_3381_20250111175914.CR2"
                tiff:Orientation="8"
                xmp:CreateDate="2025-01-11T17:59:14"
                xmp:ModifyDate="2025-01-11T17:59:14"
                >
                <dc:Type>negative film 35mm</dc:Type>
                <dc:Identifier>01/01</dc:Identifier>
                <photoshop:Instructions>mainboard:GpioZeroMainboard/xboard:GulpExtensionBoard_0103/AOT:GulpNikonStepperMotorAdapter_0103/light:GulpLight8xPWMAdapter_0103/bl_color:white/bl_intensity:52</photoshop:Instructions>
            </rdf:Description>
        </rdf:RDF>
    </x:xmpmeta>'''

if False:
    custom_tree = etree.fromstring(custom_xml)
    description = custom_tree.xpath(".//rdf:Description", namespaces=namespaces)[0]
else:
    custom_tree = etree.Element("{%s}xmpmeta" % (namespaces["x"]), nsmap={"x": namespaces["x"]})
    rdf = etree.SubElement(custom_tree, "{%s}RDF" % (namespaces["rdf"]), nsmap={"rdf": namespaces["rdf"]})
    now_s2 = "2025-30-01T10:20:30"
    description = etree.SubElement(
        rdf,
        "{%s}Description" % (namespaces["rdf"]),
        attrib={
            "{%s}about" % (namespaces["rdf"]) : "test.raw",
            "{%s}CreateDate" % (namespaces["xmp"]): now_s2,
            "{%s}ModifyDate" % (namespaces["xmp"]): now_s2,
        },
        nsmap={
            "xmp": namespaces["xmp"],
            "dc": namespaces["dc"],
            "tiff": namespaces["tiff"],
            "photoshop": namespaces["photoshop"],
        }
    )
    description.set("{%s}Orientation" % (namespaces["tiff"]), "7")
    etree.SubElement(description, "{%s}Source" % (namespaces["photoshop"])).text = "negative film 35mm"
    description.set("{%s}Identifier" % (namespaces["dc"]), "%s/%s" % (999, 11))
    etree.SubElement(description, "{%s}Instructions" % (namespaces["photoshop"])).text = "TEST INSTRUCTIONS"


print("Custom XML:\n%s" % (etree.tostring(custom_tree, pretty_print=True, encoding="utf-8").decode("utf-8")))

#print("Custom Description:\n%s" % (etree.tostring(etree.ElementTree(description), pretty_print=True).decode()))

if False:
    preset = etree.parse("preset/BW_negative.xmp")
    preset_tree = preset.getroot()
else:
    preset_tree = etree.fromstring(preset_xml)
    
print("Preset XML:\n%s" % (etree.tostring(preset_tree, pretty_print=True, encoding="utf-8").decode("utf-8")))

preset_descriptions = preset_tree.xpath(".//rdf:Description", namespaces=namespaces)
if (preset_descriptions):
    preset_description = preset_descriptions[0]
    #print("Preset Description:\n%s" % (etree.tostring(etree.ElementTree(preset_description), pretty_print=True).decode()))

    # merge namespaces, we need clone subelement as seems nsmap cannot be updated
    preset_nsmap = preset_description.nsmap
    #print(f"preset namespace: %s" % preset_nsmap)
    for prefix, uri in description.nsmap.items():
        if prefix not in preset_nsmap:
            print(f"Add namespace: {prefix}=\"{uri}\"")
            # preset_description.attrib[f"xmlns:{prefix}"] = uri
            preset_nsmap[prefix] = uri

    new_description = etree.SubElement(preset_description.getparent(), preset_description.tag, {}, preset_nsmap)
    #print(f"new preset namespace3: %s" % new_description.nsmap)    

    # copy attributes
    for attr, value in description.attrib.items():
        print("set attr: %s = %s" % (attr, value))
        new_description.set(attr, value)

    # copy subelements
    # merge elements
    elems = description.xpath("*")
    if elems:
        for elem in elems:
            elem_name = elem.tag
            print("merging elem: %s" % (elem_name))
            new_description.append(elem)

    # merge preset attributes
    for attr, value in preset_description.attrib.items():
        if attr not in new_description.attrib:
            print("merging preset attr: %s" % (attr))
            elems = new_description.findall(f"{attr}")
            if not elems:
                new_description.set(attr, value)
    # merge preset elements
    elems = preset_description.xpath("*")
    if elems:
        for elem in elems:
            elem_name = elem.tag
            print("merging elem: %s" % (elem_name))
            if elem_name not in new_description.attrib and not new_description.findall(f"{elem_name}"):
                new_description.append(elem)

    print("New Description:\n%s" % (etree.tostring(etree.ElementTree(new_description), pretty_print=True, encoding="utf-8").decode("utf-8")))
    preset_description.getparent().append(new_description)
    preset_description.getparent().remove(preset_description)

    output_tree = preset_tree
else:
    print("No preset")
    output_tree = custom_tree



print("Output XML:\n%s" % (etree.tostring(output_tree, pretty_print=True, encoding="utf-8").decode("utf-8")))

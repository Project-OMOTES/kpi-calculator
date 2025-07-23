import datetime
import os
import pathlib
import xml.etree.ElementTree as ET
from xml.dom import minidom

import xmltodict


# Class to load and read from and to PiXml files
class PiXmlTimeSeries:
    def __init__(self, time_series_xml_file, name_at, property_at, remove_name=True):
        self.time_series_xml_file = time_series_xml_file
        fname = pathlib.Path(time_series_xml_file)
        self.time_data_file = datetime.datetime.fromtimestamp(fname.stat().st_mtime)
        self.name_at = name_at
        self.property_at = property_at
        self.station_name = None
        self.time_series = {}
        # check if file exist
        if not os.path.exists(self.time_series_xml_file):
            # create new xml file
            ET.register_namespace("", "http://www.wldelft.nl/fews/PI")
            ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
            root = ET.Element("TimeSeries")
            timezone = ET.SubElement(root, "timeZone")
            timezone.text = str(0)
            line = ET.tostring(root).replace(b"\n", b"")
            line = line.replace(b"@", b"")
            xmlstr = minidom.parseString(line).toprettyxml(indent="   ")
            with open(self.time_series_xml_file, "w") as f:
                f.write(xmlstr)
        with open(self.time_series_xml_file) as fd:
            xml_dict = xmltodict.parse(fd.read())
        self.time_zone = float(xml_dict["TimeSeries"]["timeZone"])

        # parsing timeseries
        # if there is only one time series or multiple.
        if "series" not in xml_dict["TimeSeries"]:
            return
        # if there is only one time series or multiple.
        if "header" in xml_dict["TimeSeries"]["series"]:
            # there is only one timerseries
            name = xml_dict["TimeSeries"]["series"]["header"][name_at]
            prop_name = xml_dict["TimeSeries"]["series"]["header"][property_at]
            time_series = TimeSeries()
            time_series.parse_existing(
                xml_dict["TimeSeries"]["series"]["header"], name_at, property_at
            )
            if "event" in xml_dict["TimeSeries"]["series"]:
                time_series.parse_time_series(xml_dict["TimeSeries"]["series"]["event"])
            self.time_series[name] = {prop_name: time_series}
        else:
            for time_serie in xml_dict["TimeSeries"]["series"]:
                name = time_serie["header"][name_at]
                prop_name = time_serie["header"][property_at]
                series = TimeSeries()
                series.parse_existing(time_serie["header"], name_at, property_at)
                if "event" in time_serie:
                    series.parse_time_series(time_serie["event"])
                if name in self.time_series:
                    self.time_series[name][prop_name] = series
                else:
                    self.time_series[name] = {prop_name: series}

                if remove_name:
                    ind = series.header_dict["locationId"].rfind("_")
                    self.station_name = series.header_dict["locationId"][0:ind]
                else:
                    self.station_name = series.header_dict["locationId"]

    def add_timer_series(
        self,
        pi_xml_type,
        location_id,
        parameter_id,
        qualifier_id,
        time_step,
        start_date,
        end_date,
        forecast_date,
        miss_val,
        station_name,
        lat,
        lon,
        x,
        y,
        z,
        units,
        creation_date,
        creation_time,
    ):
        time_series = TimeSeries(
            pi_xml_type,
            location_id,
            parameter_id,
            qualifier_id,
            time_step,
            start_date,
            end_date,
            forecast_date,
            miss_val,
            station_name,
            lat,
            lon,
            x,
            y,
            z,
            units,
            creation_date,
            creation_time,
        )
        time_series.name = time_series.header_dict[self.name_at]
        time_series.prop = time_series.header_dict[self.property_at]
        if time_series.name in self.time_series:
            self.time_series[time_series.name][time_series.prop] = time_series
        else:
            self.time_series[time_series.name] = {time_series.prop: time_series}
        return self.time_series[time_series.name][time_series.prop]

    def save_to_XML(self, file=None):
        ET.register_namespace("", "http://www.wldelft.nl/fews/PI")
        ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
        # loading xml output file
        tree = ET.parse(self.time_series_xml_file)
        root = tree.getroot()
        # finding location to save the KPI
        for name in self.time_series:
            for prop in self.time_series[name]:
                if self.time_series[name][prop].new_element:
                    series_element = ET.SubElement(root, "series")
                    self.time_series[name][prop].save_series(series_element)
                else:
                    for series_element in root.iter("{http://www.wldelft.nl/fews/PI}series"):
                        name_ET = (
                            series_element[0]
                            .find("{http://www.wldelft.nl/fews/PI}" + self.name_at)
                            .text
                        )
                        prop_ET = (
                            series_element[0]
                            .find("{http://www.wldelft.nl/fews/PI}" + self.property_at)
                            .text
                        )
                        if (name == name_ET) & (prop == prop_ET):
                            self.time_series[name][prop].save_series(series_element)

        if file is None:
            output_file = self.time_series_xml_file
        else:
            output_file = file

        line = ET.tostring(root).replace(b"\n", b"")
        line = line.replace(b"@", b"")
        xmlstr = minidom.parseString(line).toprettyxml(indent="   ")
        with open(output_file, "w") as f:
            f.write(xmlstr)


def check_header(header, object_name):
    if object_name in header:
        return header[object_name]
    else:
        return None


# class which holds a complete time series object
class TimeSeries:
    def __init__(
        self,
        pi_xml_type=None,
        location_id=None,
        parameter_id=None,
        qualifier_id=None,
        time_step=None,
        start_date=None,
        end_date=None,
        forecast_date=None,
        miss_val=None,
        station_name=None,
        lat=None,
        lon=None,
        x=None,
        y=None,
        z=None,
        units=None,
        creation_date=None,
        creation_time=None,
        name=None,
        prop=None,
    ):
        self.header_dict = {
            "type": pi_xml_type,
            "locationId": location_id,
            "parameterId": parameter_id,
            "qualifierId": qualifier_id,
            "timeStep": time_step,
            "startDate": start_date,
            "endDate": end_date,
            "forecastDate": forecast_date,
            "missVal": miss_val,
            "stationName": station_name,
            "lat": lat,
            "lon": lon,
            "x": x,
            "y": y,
            "z": z,
            "units": units,
            "creationDate": creation_date,
            "creationTime": creation_time,
        }
        self.name = None
        self.prop = None
        self.new_element = True
        self.events = []
        self.object_list = [
            "type",
            "locationId",
            "parameterId",
            "qualifierId",
            "timeStep",
            "startDate",
            "endDate",
            "forecastDate",
            "missVal",
            "stationName",
            "lat",
            "lon",
            "x",
            "y",
            "z",
            "units",
            "creationDate",
            "creationTime",
        ]

    def parse_existing(self, header_object, name_at, prop_at):
        self.header_dict = {}
        for item in self.object_list:
            self.header_dict[item] = check_header(header_object, item)
        self.new_element = False
        self.name = self.header_dict[name_at]
        self.prop = self.header_dict[prop_at]

    def parse_time_series(self, event_object):
        self.events = []
        # check if only one event is in the list:
        if "@date" in event_object:
            self.events.append(
                PiXmlEvent(
                    event_object["@date"],
                    event_object["@time"],
                    float(event_object["@value"]),
                    int(float(event_object["@flag"])),
                )
            )
        else:
            for event in event_object:
                self.events.append(
                    PiXmlEvent(
                        event["@date"],
                        event["@time"],
                        float(event["@value"]),
                        int(float(event["@flag"])),
                    )
                )
        return self.events

    def add_event(self, date, time, value, flag):
        # ToDO check input!
        self.events.append(PiXmlEvent(date, time, value, flag, True))

    def save_series(self, element):
        if self.new_element:
            header = ET.SubElement(element, "header")
            for item in self.object_list:
                if isinstance(self.header_dict[item], dict):
                    elem = ET.SubElement(header, item)
                    for dict_item in self.header_dict[item]:
                        elem.set(dict_item, self.header_dict[item][dict_item])
                else:
                    elem = ET.SubElement(header, item)
                    elem.text = str(self.header_dict[item])
            self.new_element = False
        # safe events
        for event in self.events:
            event.save_event(element)

    def get_time_step(self):
        time1 = datetime.datetime.strptime(
            self.events[0].date + " " + self.events[0].time, "%Y-%m-%d %H:%M:%S"
        )
        if len(self.events) > 1:
            time2 = datetime.datetime.strptime(
                self.events[1].date + " " + self.events[1].time, "%Y-%m-%d %H:%M:%S"
            )
        else:
            return 3600 * 24 * 7  # assume for now 1 week time step, which is the default in CF
        return (time2 - time1).total_seconds()

    def get_series_as_list(self):
        return [event.value for event in self.events]


# class for PiXmlevent, which is in the Timerseries
class PiXmlEvent:
    def __init__(self, date, time, value, flag, new_event=False):
        self.date = date
        self.time = time
        self.value = value
        self.flag = flag
        self.new_event = new_event

    def save_event(self, element):
        if self.new_event:
            event_element = ET.SubElement(element, "event")
            event_element.attrib = {
                "date": str(self.date),
                "flag": str(self.flag),
                "time": str(self.time),
                "value": str(self.value),
            }


def main():
    pixml = (
        r"d:\repos\warmingUp\KPI_calculator\kpi-calculator\KPI_calculator_server"
        r"\swagger_server\test\test_case\alpha1\to_kpicalculator\power_timeseries2.xml"
    )
    pixml_object = PiXmlTimeSeries(pixml, "locationId", "parameterId")
    timeseries = pixml_object.add_timer_series(
        "continuous",
        "somewhere",
        "something",
        "OK",
        200,
        "20-10-2020",
        "21-10-2020",
        "20-10-2020",
        -999,
        "hello",
        0,
        0,
        10,
        -10,
        50,
        "m3/h",
        "20-10-2020",
        "10:00",
    )
    timeseries.add_event("10", "10:00", 100, 1)
    pixml_object.save_to_XML("klaas.xml")


if __name__ == "__main__":
    main()

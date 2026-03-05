import datetime
import os
import xml.etree.ElementTree as ET
from typing import Any
from xml.dom import minidom

import xmltodict  # type: ignore[import-untyped]

from ..common.constants import DEFAULT_WEEK_TIME_STEP, HTTP_SCHEMA_URL
from .time_series_protocols import TimeSeriesProvider


# Class to load and read from and to PiXml files
class PiXmlTimeSeries(TimeSeriesProvider):
    def __init__(
        self,
        time_series_xml_file: str,
        name_at: str,
        property_at: str,
        remove_name: bool = True,
    ) -> None:
        self.time_series_xml_file: str = time_series_xml_file
        self.name_at: str = name_at
        self.property_at: str = property_at
        self.station_name: str | None = None
        self._time_series_internal: dict[str, Any] = {}
        # check if file exist
        if not os.path.exists(self.time_series_xml_file):
            # create new xml file
            ET.register_namespace("", "http://www.wldelft.nl/fews/PI")
            ET.register_namespace("xsi", HTTP_SCHEMA_URL)
            root = ET.Element("TimeSeries")
            timezone = ET.SubElement(root, "timeZone")
            timezone.text = str(0)
            line = ET.tostring(root).replace(b"\n", b"")
            line = line.replace(b"@", b"")
            xmlstr = minidom.parseString(line).toprettyxml(indent="   ")
            with open(self.time_series_xml_file, "w", encoding="utf-8") as f:
                f.write(xmlstr)
        with open(self.time_series_xml_file, encoding="utf-8") as fd:
            xml_dict = xmltodict.parse(fd.read())

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
            self._time_series_internal[name] = {prop_name: time_series}
        else:
            for time_serie in xml_dict["TimeSeries"]["series"]:
                name = time_serie["header"][name_at]
                prop_name = time_serie["header"][property_at]
                series = TimeSeries()
                series.parse_existing(time_serie["header"], name_at, property_at)
                if "event" in time_serie:
                    series.parse_time_series(time_serie["event"])
                if name in self._time_series_internal:
                    self._time_series_internal[name][prop_name] = series
                else:
                    self._time_series_internal[name] = {prop_name: series}

                if remove_name:
                    ind = series.header_dict["locationId"].rfind("_")
                    self.station_name = series.header_dict["locationId"][0:ind]
                else:
                    self.station_name = series.header_dict["locationId"]

    def get_time_series(self, asset_id: str) -> list[float] | None:
        """Get time series data for a specific asset.

        Args:
            asset_id: Asset identifier to retrieve time series for

        Returns:
            List of numeric values if data exists, None otherwise
        """
        # Check if asset_id exists in the nested structure
        if asset_id in self._time_series_internal:
            asset_data = self._time_series_internal[asset_id]
            if isinstance(asset_data, dict) and asset_data:
                # TimeSeries constructor guarantees 'events' attribute exists
                first_prop = next(iter(asset_data.values()))
                if first_prop.events:  # Check if events list is non-empty
                    return [float(event.value) for event in first_prop.events]
        return None

    @property
    def time_series(self) -> dict[str, list[float]]:
        """Access to all available time series data.

        Returns:
            Dictionary mapping asset IDs to their time series data as lists of floats
        """
        result: dict[str, list[float]] = {}

        for asset_id, asset_data in self._time_series_internal.items():
            if isinstance(asset_data, dict) and asset_data:
                # TimeSeries constructor guarantees 'events' attribute exists
                first_prop = next(iter(asset_data.values()))
                if first_prop.events:  # Check if events list is non-empty
                    try:
                        result[asset_id] = [float(event.value) for event in first_prop.events]
                    except (ValueError, TypeError):
                        # Skip assets with invalid numeric conversion
                        continue

        return result

    def get_time_series_with_parameters(self) -> dict[str, dict[str, tuple[list[float], float]]]:
        """Get all time series data organized by asset and parameter with time step info.

        Returns:
            Dictionary mapping asset_id -> parameter_name -> (values, time_step)
            Example: {"asset_1": {"ThermalConsumption": ([10.0, 20.0], 3600.0)}}
        """
        result: dict[str, dict[str, tuple[list[float], float]]] = {}

        for asset_id, prop_data in self._time_series_internal.items():
            if isinstance(prop_data, dict) and prop_data:
                asset_parameters: dict[str, tuple[list[float], float]] = {}
                for parameter_name, series in prop_data.items():
                    if hasattr(series, "events") and series.events:
                        try:
                            values = [float(event.value) for event in series.events]
                            time_step = series.get_time_step()
                            asset_parameters[parameter_name] = (values, time_step)
                        except (ValueError, TypeError):
                            # Skip parameters with invalid numeric conversion
                            continue

                if asset_parameters:
                    result[asset_id] = asset_parameters

        return result

    def add_timer_series(
        self,
        pi_xml_type: str,
        location_id: str,
        parameter_id: str,
        qualifier_id: str,
        time_step: int | str,
        start_date: str,
        end_date: str,
        forecast_date: str,
        miss_val: int | float,
        station_name: str,
        lat: int | float,
        lon: int | float,
        x: int | float,
        y: int | float,
        z: int | float,
        units: str,
        creation_date: str,
        creation_time: str,
    ) -> "TimeSeries":
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
        if time_series.name is not None and time_series.prop is not None:
            if time_series.name in self._time_series_internal:
                self._time_series_internal[time_series.name][time_series.prop] = time_series
            else:
                self._time_series_internal[time_series.name] = {time_series.prop: time_series}
            return self._time_series_internal[time_series.name][time_series.prop]
        return time_series

    def save_to_XML(self, file: str | None = None) -> None:
        ET.register_namespace("", "http://www.wldelft.nl/fews/PI")
        ET.register_namespace("xsi", HTTP_SCHEMA_URL)
        # loading xml output file
        tree = ET.parse(self.time_series_xml_file)
        root = tree.getroot()
        # finding location to save the KPI
        for name in self._time_series_internal:
            for prop in self._time_series_internal[name]:
                if self._time_series_internal[name][prop].new_element:
                    series_element = ET.SubElement(root, "series")
                    self._time_series_internal[name][prop].save_series(series_element)
                else:
                    for series_element in root.iter("{http://www.wldelft.nl/fews/PI}series"):
                        name_element = series_element[0].find(
                            "{http://www.wldelft.nl/fews/PI}" + self.name_at
                        )
                        prop_element = series_element[0].find(
                            "{http://www.wldelft.nl/fews/PI}" + self.property_at
                        )

                        name_ET = name_element.text if name_element is not None else None
                        prop_ET = prop_element.text if prop_element is not None else None
                        if (name == name_ET) and (prop == prop_ET):
                            self._time_series_internal[name][prop].save_series(series_element)

        output_file = self.time_series_xml_file if file is None else file

        line = ET.tostring(root).replace(b"\n", b"")
        line = line.replace(b"@", b"")
        xmlstr = minidom.parseString(line).toprettyxml(indent="   ")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(xmlstr)


def check_header(header: dict[str, Any], object_name: str) -> Any:
    if object_name in header:
        return header[object_name]
    return None


# class which holds a complete time series object
class TimeSeries:
    def __init__(
        self,
        pi_xml_type: Any = None,
        location_id: Any = None,
        parameter_id: Any = None,
        qualifier_id: Any = None,
        time_step: Any = None,
        start_date: Any = None,
        end_date: Any = None,
        forecast_date: Any = None,
        miss_val: Any = None,
        station_name: Any = None,
        lat: Any = None,
        lon: Any = None,
        x: Any = None,
        y: Any = None,
        z: Any = None,
        units: Any = None,
        creation_date: Any = None,
        creation_time: Any = None,
        name: Any = None,
        prop: Any = None,
    ) -> None:
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
        self.events: list[PiXmlEvent] = []
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

    def parse_existing(self, header_object: dict[str, Any], name_at: str, prop_at: str) -> None:
        self.header_dict = {}
        for item in self.object_list:
            self.header_dict[item] = check_header(header_object, item)
        self.new_element = False
        self.name = self.header_dict[name_at]
        self.prop = self.header_dict[prop_at]

    def parse_time_series(
        self, event_object: dict[str, Any] | list[dict[str, Any]]
    ) -> list["PiXmlEvent"]:
        self.events.clear()
        # check if only one event is in the list:
        if isinstance(event_object, dict) and "@date" in event_object:
            self.events.append(
                PiXmlEvent(
                    event_object["@date"],
                    event_object["@time"],
                    float(event_object["@value"]),
                    int(float(event_object["@flag"])),
                )
            )
        else:
            for event in event_object:  # type: ignore[union-attr]
                event_dict: dict[str, Any] = event  # type: ignore[assignment]
                self.events.append(
                    PiXmlEvent(
                        event_dict["@date"],
                        event_dict["@time"],
                        float(event_dict["@value"]),
                        int(float(event_dict["@flag"])),
                    )
                )
        return self.events

    def add_event(self, date: str, time: str, value: float, flag: int) -> None:
        # ToDO check input!
        self.events.append(PiXmlEvent(date, time, value, flag, True))

    def save_series(self, element: ET.Element) -> None:
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

    def get_time_step(self) -> float:
        time1 = datetime.datetime.strptime(
            self.events[0].date + " " + self.events[0].time, "%Y-%m-%d %H:%M:%S"
        )
        if len(self.events) > 1:
            time2 = datetime.datetime.strptime(
                self.events[1].date + " " + self.events[1].time, "%Y-%m-%d %H:%M:%S"
            )
        else:
            # assume for now 1 week time step, which is the default in CF
            return DEFAULT_WEEK_TIME_STEP
        return (time2 - time1).total_seconds()


# class for PiXmlevent, which is in the Timerseries
class PiXmlEvent:
    def __init__(
        self, date: str, time: str, value: float, flag: int, new_event: bool = False
    ) -> None:
        self.date = date
        self.time = time
        self.value = value
        self.flag = flag
        self.new_event = new_event

    def save_event(self, element: ET.Element) -> None:
        if self.new_event:
            event_element = ET.SubElement(element, "event")
            event_element.set("date", str(self.date))
            event_element.set("flag", str(self.flag))
            event_element.set("time", str(self.time))
            event_element.set("value", str(self.value))

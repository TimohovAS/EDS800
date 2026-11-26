"""Native FC telegram fixtures and a serial double; never opens a COM port."""
from dataclasses import replace
from functools import reduce
from operator import xor
import threading
import unittest
from unittest.mock import Mock, patch

import serial

from enc_editor.catalog import load_catalog
from enc_editor.codecs import READ_ERROR, format_value
from enc_editor.diagnostics import ResetRefused
from enc_editor.fc_protocol import FCLink, FCProtocolError, build_request, parse_response
from enc_editor.transport import LinkError, ModbusLink, TaskCancelled, create_link

PROFILE = load_catalog()["danfoss_fc51"]
PARAMETERS = PROFILE.by_code()


def response(request, value=0, command=1, text=None, status=0x0203):
    pke = (command << 12) | (int.from_bytes(request[3:5], "big") & 0xFFF)
    data = pke.to_bytes(2, "big") + request[5:7]
    data += text if text is not None else value.to_bytes(4, "big")
    data += status.to_bytes(2, "big") + b"\0\0"
    packet = bytes((2, len(data) + 2, request[2])) + data
    return packet + bytes((reduce(xor, packet, 0),))


class SerialDouble:
    def __init__(self, answer, fragment=256):
        self.answer, self.fragment = answer, fragment
        self.sent = []
        self.buffer = bytearray()
        self.closed = False

    @property
    def in_waiting(self):
        return len(self.buffer)

    def reset_input_buffer(self):
        self.buffer.clear()

    def write(self, data):
        self.sent.append(data)
        self.buffer.extend(self.answer(data))
        return len(data)

    def flush(self):
        pass

    def read(self, count):
        count = min(count, self.fragment)
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        return data

    def close(self):
        self.closed = True


class TelegramTests(unittest.TestCase):
    def test_manual_read_example_pnu_341(self):
        request = build_request(1, PARAMETERS["3-41"])
        self.assertEqual(request, bytes.fromhex("02 0E 81 11 55 00 00 00 00 00 00 00 00 00 00 C9"))
        reply = bytes.fromhex("02 0E 81 11 55 00 00 00 00 03 E8 00 00 00 00 22")
        self.assertEqual(parse_response(reply, request, PARAMETERS["3-41"]), 1000)

    def test_manual_eeprom_word_write_pnu_414(self):
        request = build_request(1, PARAMETERS["4-14"], command=14, value=1000)
        self.assertEqual(request, bytes.fromhex("02 0E 81 E1 9E 00 00 00 00 03 E8 00 00 00 00 19"))

    def test_every_parameter_request_has_invalid_control_word_and_zero_reference(self):
        for p in PROFILE.parameters:
            for command in (1, 13, 14, 15):
                with self.subTest(code=p["code"], command=command):
                    request = build_request(126, p, command)
                    self.assertEqual(request[-5:-1], b"\0\0\0\0")
                    self.assertEqual(request[2], 0xFE)
                    self.assertEqual(reduce(xor, request, 0), 0)

    def test_array_index_is_in_ind_low_byte_not_a_register_write(self):
        request = build_request(7, PARAMETERS["15-30[9]"])
        self.assertEqual(request[5:7], b"\0\x09")
        self.assertEqual(request[2], 0x87)
        self.assertEqual(int.from_bytes(request[3:5], "big") & 0xFFF, 1530)

    def test_text_command_and_ind_read_flag(self):
        p = PARAMETERS["15-43"]
        request = build_request(1, p, command=15)
        self.assertEqual(request[3] >> 4, 15)
        self.assertEqual(request[5:7], b"\x04\0")
        raw = parse_response(response(request, command=15, text=b"FC 51 2.70"), request, p)
        self.assertEqual(format_value(raw, p), "FC 51 2.70")

    def test_full_width_text_and_overlong_text(self):
        p = PARAMETERS["15-43"]
        request = build_request(1, p, command=15)
        text = b"12345678901234567890"
        self.assertEqual(parse_response(response(request, command=15, text=text), request, p),
                         int.from_bytes(text, "big"))
        with self.assertRaises(FCProtocolError):
            parse_response(response(request, command=15, text=text + b"x"), request, p)

    def test_signed_and_unsigned_double_words_are_packed_without_truncation(self):
        for code, value in (("3-02", 0xFFFFAFEC), ("16-90", 0x80000000)):
            p = PARAMETERS[code]
            request = build_request(1, p)
            self.assertEqual(parse_response(response(request, value, command=2), request, p), value)

    def test_word_response_ignores_undefined_high_word(self):
        p = PARAMETERS["4-14"]
        request = build_request(1, p)
        self.assertEqual(parse_response(response(request, 0xDEAD03E8), request, p), 1000)

    def test_response_cannot_overflow_declared_type(self):
        p = PARAMETERS["15-30[0]"]
        request = build_request(1, p)
        with self.assertRaises(FCProtocolError):
            parse_response(response(request, 256), request, p)

    def test_slave_error_code_is_preserved(self):
        p = PARAMETERS["4-14"]
        request = build_request(1, p)
        with self.assertRaises(FCProtocolError) as caught:
            parse_response(response(request, 17, command=7), request, p)
        self.assertEqual(caught.exception.key, "fc.rejected")
        self.assertEqual(caught.exception.params, {"code": 17})

    def test_rejects_checksum_length_address_pnu_and_index_mismatches(self):
        p = PARAMETERS["15-30[0]"]
        request = build_request(1, p)
        original = response(request, 13)
        for position in (0, 1, 2, 4, 6, 15):
            bad = bytearray(original)
            bad[position] ^= 1
            if position not in (0, 1, 15):
                bad[-1] = reduce(xor, bad[:-1], 0)
            with self.subTest(position=position), self.assertRaises(FCProtocolError):
                parse_response(bytes(bad), request, p)

    def test_no_broadcast_out_of_range_index_or_unsupported_command(self):
        p = PARAMETERS["4-14"]
        for address in (0, 127, 247, -1):
            with self.assertRaises(ValueError):
                build_request(address, p)
        for command in (0, 2, 3, 16):
            with self.assertRaises(ValueError):
                build_request(1, p, command)
        with self.assertRaises(ValueError):
            build_request(1, dict(p, array_index=256))


class NativeTransportTests(unittest.TestCase):
    def link(self, answer=None, fragment=256):
        link = FCLink("not-a-real-port", 1, replace(PROFILE.link, timeout=0.02))
        link.client = SerialDouble(answer or (lambda request: response(request, 50)), fragment)
        return link

    def test_factory_selects_protocol_without_opening_port(self):
        with patch("enc_editor.fc_protocol.serial.Serial") as port:
            self.assertIsInstance(create_link("test", 1, PROFILE.link), FCLink)
            self.assertIsInstance(create_link("test", 1, PROFILE.link_for_protocol("modbus_rtu")), ModbusLink)
        port.assert_not_called()

    def test_serial_open_settings_and_close(self):
        link = FCLink("test", 1, PROFILE.link)
        with patch("enc_editor.fc_protocol.serial.Serial") as port:
            client = port.return_value
            with link:
                port.assert_called_once_with(port="test", baudrate=9600, bytesize=8, parity="E",
                                             stopbits=1, timeout=0.05, write_timeout=1.0)
            client.close.assert_called_once()
            self.assertIsNone(link.client)

    def test_open_failure_is_an_open_port_error(self):
        with patch("enc_editor.fc_protocol.serial.Serial", side_effect=serial.SerialException("busy")):
            with self.assertRaises(LinkError):
                FCLink("test", 1, PROFILE.link).open()

    def test_read_fragmented_response_after_noise_and_echo(self):
        link = self.link(lambda request: b"noise" + request + response(request, 123), fragment=1)
        self.assertEqual(link.read_parameter(PARAMETERS["4-14"]), 123)
        self.assertEqual(len(link.client.sent), 1)

    def test_unrelated_or_bad_checksum_reply_does_not_hide_good_reply(self):
        def answers(request):
            other = build_request(2, PARAMETERS["4-14"])
            corrupt = bytearray(response(request, 20))
            corrupt[-1] ^= 1
            return response(other, 10) + corrupt + response(request, 30)
        link = self.link(answers)
        self.assertEqual(link.read_parameter(PARAMETERS["4-14"]), 30)

    def test_echo_only_never_becomes_a_zero_value(self):
        link = self.link(lambda request: request)
        with self.assertRaises(FCProtocolError) as caught:
            link.read_parameter(PARAMETERS["4-14"])
        self.assertEqual(caught.exception.key, "fc.echo_only")

    def test_timeout_and_partial_packet_never_become_zero(self):
        for answer in (lambda request: b"", lambda request: response(request)[:9]):
            link = self.link(answer)
            values = link.read_values([PARAMETERS["4-14"]])
            self.assertEqual(values, {"4-14": READ_ERROR})
            self.assertEqual(len(link.client.sent), 1)

    def test_true_zero_reply_with_status_is_accepted(self):
        link = self.link(lambda request: response(request, 0))
        self.assertEqual(link.read_parameter(PARAMETERS["4-14"]), 0)

    def test_indexed_read_does_not_write_any_parameter_or_index_register(self):
        link = self.link(lambda request: response(request, request[6]))
        params = [PARAMETERS["15-30[0]"], PARAMETERS["15-30[9]"]]
        self.assertEqual(link.read_values(params), {"15-30[0]": 0, "15-30[9]": 9})
        self.assertEqual([packet[3] >> 4 for packet in link.client.sent], [1, 1])
        self.assertEqual([packet[6] for packet in link.client.sent], [0, 9])

    def test_word_and_double_word_writes_use_documented_eeprom_commands(self):
        link = self.link(lambda request: response(request, int.from_bytes(request[7:11], "big"),
                                                  command=2 if request[3] >> 4 == 13 else 1))
        targets = [(PARAMETERS["4-14"], 1000, "100"), (PARAMETERS["3-02"], 0xFFFFAFEC, "-20.500")]
        result = link.write_values(targets)
        self.assertFalse(result["failed"])
        self.assertEqual(result["written"], {"4-14": 1000, "3-02": 0xFFFFAFEC})
        self.assertEqual([packet[3] >> 4 for packet in link.client.sent], [14, 13])
        self.assertTrue(all(packet[-5:-1] == b"\0\0\0\0" for packet in link.client.sent))

    def test_failed_write_is_not_retried_or_marked_successful(self):
        link = self.link(lambda request: response(request, 1, command=7))
        result = link.write_values([(PARAMETERS["4-14"], 1000, "100")])
        self.assertFalse(result["written"])
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(len(link.client.sent), 1)

    def test_timeout_during_write_is_never_retried(self):
        link = self.link(lambda request: b"")
        result = link.write_values([(PARAMETERS["4-14"], 1000, "100")])
        self.assertFalse(result["written"])
        self.assertEqual(len(link.client.sent), 1)

    def test_readonly_and_out_of_storage_values_never_transmit(self):
        link = self.link()
        result = link.write_values([(PARAMETERS["16-90"], 0, "0"), (PARAMETERS["4-14"], 65536, "65536")])
        self.assertEqual(len(result["failed"]), 2)
        self.assertEqual(link.client.sent, [])

    def test_communication_changes_remain_last(self):
        link = self.link(lambda request: response(request, int.from_bytes(request[7:11], "big")))
        link.write_values([(PARAMETERS["8-31"], 2, "2"), (PARAMETERS["1-23"], 50, "50")])
        self.assertEqual([int.from_bytes(p[3:5], "big") & 0xFFF for p in link.client.sent], [123, 831])

    def test_wrong_write_ack_is_not_marked_written_or_retried(self):
        link = self.link(lambda request: response(request, 999))
        result = link.write_values([(PARAMETERS["4-14"], 1000, "100")])
        self.assertEqual(result["written"], {})
        self.assertIn("fc.write_unverified", result["failed"][0][1])
        self.assertEqual(len(link.client.sent), 1)

    def test_cancel_before_work_or_between_reads_stops_transmission(self):
        link = self.link()
        link.cancel.set()
        with self.assertRaises(TaskCancelled):
            link.read_parameter(PARAMETERS["4-14"])
        self.assertEqual(link.client.sent, [])
        link.cancel.clear()
        with self.assertRaises(TaskCancelled):
            link.read_values([PARAMETERS["4-14"], PARAMETERS["1-23"]],
                             progress=lambda *_: link.cancel.set())
        self.assertEqual(len(link.client.sent), 1)

    def test_native_fc_reset_is_explicitly_unsupported_and_never_transmits(self):
        link = self.link()
        with self.assertRaises(ResetRefused):
            link.reset_fc_trip(PARAMETERS["16-03"])
        self.assertEqual(link.client.sent, [])


if __name__ == "__main__":
    unittest.main()

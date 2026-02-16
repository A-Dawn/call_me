import io
import struct
from dataclasses import dataclass
from enum import IntEnum


class MessageType(IntEnum):
    FULL_CLIENT_REQUEST = 0x1
    FULL_SERVER_RESPONSE = 0x9
    AUDIO_ONLY_SERVER = 0xB
    ERROR = 0xF


class MessageFlag(IntEnum):
    NO_SEQ = 0x0
    POSITIVE_SEQ = 0x1
    LAST_NO_SEQ = 0x2
    NEGATIVE_SEQ = 0x3
    WITH_EVENT = 0x4


class EventType(IntEnum):
    START_CONNECTION = 1
    FINISH_CONNECTION = 2

    CONNECTION_STARTED = 50
    CONNECTION_FAILED = 51
    CONNECTION_FINISHED = 52

    START_SESSION = 100
    FINISH_SESSION = 102

    SESSION_STARTED = 150
    SESSION_FINISHED = 152
    SESSION_FAILED = 153

    TASK_REQUEST = 200


class Serialization(IntEnum):
    RAW = 0x0
    JSON = 0x1


class Compression(IntEnum):
    NONE = 0x0


@dataclass
class ProtocolMessage:
    msg_type: MessageType
    flag: MessageFlag
    payload: bytes = b""
    event: int = 0
    session_id: str = ""
    connect_id: str = ""
    sequence: int = 0
    error_code: int = 0
    version: int = 1
    header_size: int = 1
    serialization: Serialization = Serialization.JSON
    compression: Compression = Compression.NONE


def _write_int32(buffer: io.BytesIO, value: int) -> None:
    buffer.write(struct.pack(">i", int(value)))


def _write_uint32(buffer: io.BytesIO, value: int) -> None:
    buffer.write(struct.pack(">I", int(value)))


def _read_int32(buffer: io.BytesIO) -> int:
    data = buffer.read(4)
    if len(data) != 4:
        raise ValueError("not enough bytes for int32")
    return struct.unpack(">i", data)[0]


def _read_uint32(buffer: io.BytesIO) -> int:
    data = buffer.read(4)
    if len(data) != 4:
        raise ValueError("not enough bytes for uint32")
    return struct.unpack(">I", data)[0]


def _write_string(buffer: io.BytesIO, value: str) -> None:
    payload = (value or "").encode("utf-8")
    _write_uint32(buffer, len(payload))
    if payload:
        buffer.write(payload)


def _read_string(buffer: io.BytesIO) -> str:
    size = _read_uint32(buffer)
    if size == 0:
        return ""
    data = buffer.read(size)
    if len(data) != size:
        raise ValueError("invalid string size in frame")
    return data.decode("utf-8", errors="ignore")


def encode_message(message: ProtocolMessage) -> bytes:
    buffer = io.BytesIO()

    header = [
        ((message.version & 0xF) << 4) | (message.header_size & 0xF),
        ((int(message.msg_type) & 0xF) << 4) | (int(message.flag) & 0xF),
        ((int(message.serialization) & 0xF) << 4) | (int(message.compression) & 0xF),
    ]
    header_bytes = 4 * int(message.header_size)
    if header_bytes < 3:
        raise ValueError("header_size is too small")
    if header_bytes > 3:
        header.extend([0] * (header_bytes - 3))
    buffer.write(bytes(header))

    if message.flag == MessageFlag.WITH_EVENT:
        _write_int32(buffer, int(message.event))
        if int(message.event) not in (
            EventType.START_CONNECTION,
            EventType.FINISH_CONNECTION,
            EventType.CONNECTION_STARTED,
            EventType.CONNECTION_FAILED,
            EventType.CONNECTION_FINISHED,
        ):
            _write_string(buffer, message.session_id)
        if int(message.event) in (
            EventType.CONNECTION_STARTED,
            EventType.CONNECTION_FAILED,
            EventType.CONNECTION_FINISHED,
        ):
            _write_string(buffer, message.connect_id)

    if message.msg_type in (MessageType.FULL_CLIENT_REQUEST, MessageType.FULL_SERVER_RESPONSE, MessageType.AUDIO_ONLY_SERVER):
        if message.flag in (MessageFlag.POSITIVE_SEQ, MessageFlag.NEGATIVE_SEQ):
            _write_int32(buffer, message.sequence)
    elif message.msg_type == MessageType.ERROR:
        _write_uint32(buffer, message.error_code)
    else:
        raise ValueError(f"unsupported message type: {message.msg_type}")

    _write_uint32(buffer, len(message.payload))
    if message.payload:
        buffer.write(message.payload)
    return buffer.getvalue()


def decode_message(data: bytes) -> ProtocolMessage:
    if len(data) < 3:
        raise ValueError("frame is too short")

    buffer = io.BytesIO(data)
    version_and_header = buffer.read(1)[0]
    version = (version_and_header >> 4) & 0xF
    header_size = version_and_header & 0xF
    if header_size < 1:
        raise ValueError("invalid header size")

    type_and_flag = buffer.read(1)[0]
    msg_type = MessageType((type_and_flag >> 4) & 0xF)
    flag = MessageFlag(type_and_flag & 0xF)

    serialization_and_compression = buffer.read(1)[0]
    serialization = Serialization((serialization_and_compression >> 4) & 0xF)
    compression = Compression(serialization_and_compression & 0xF)

    padding = (header_size * 4) - 3
    if padding > 0:
        skipped = buffer.read(padding)
        if len(skipped) != padding:
            raise ValueError("invalid header padding")

    message = ProtocolMessage(
        msg_type=msg_type,
        flag=flag,
        version=version,
        header_size=header_size,
        serialization=serialization,
        compression=compression,
    )

    if flag == MessageFlag.WITH_EVENT:
        message.event = _read_int32(buffer)
        if message.event not in (
            EventType.START_CONNECTION,
            EventType.FINISH_CONNECTION,
            EventType.CONNECTION_STARTED,
            EventType.CONNECTION_FAILED,
            EventType.CONNECTION_FINISHED,
        ):
            message.session_id = _read_string(buffer)
        if message.event in (
            EventType.CONNECTION_STARTED,
            EventType.CONNECTION_FAILED,
            EventType.CONNECTION_FINISHED,
        ):
            message.connect_id = _read_string(buffer)

    if msg_type in (MessageType.FULL_CLIENT_REQUEST, MessageType.FULL_SERVER_RESPONSE, MessageType.AUDIO_ONLY_SERVER):
        if flag in (MessageFlag.POSITIVE_SEQ, MessageFlag.NEGATIVE_SEQ):
            message.sequence = _read_int32(buffer)
    elif msg_type == MessageType.ERROR:
        message.error_code = _read_uint32(buffer)
    else:
        raise ValueError(f"unsupported message type: {msg_type}")

    payload_size = _read_uint32(buffer)
    if payload_size > 0:
        payload = buffer.read(payload_size)
        if len(payload) != payload_size:
            raise ValueError("invalid payload size")
        message.payload = payload
    else:
        message.payload = b""

    trailing = buffer.read()
    if trailing:
        raise ValueError("unexpected trailing bytes in frame")

    return message


def build_start_connection() -> bytes:
    return encode_message(
        ProtocolMessage(
            msg_type=MessageType.FULL_CLIENT_REQUEST,
            flag=MessageFlag.WITH_EVENT,
            event=EventType.START_CONNECTION,
            payload=b"{}",
        )
    )


def build_start_session(session_id: str, payload: bytes) -> bytes:
    return encode_message(
        ProtocolMessage(
            msg_type=MessageType.FULL_CLIENT_REQUEST,
            flag=MessageFlag.WITH_EVENT,
            event=EventType.START_SESSION,
            session_id=session_id,
            payload=payload,
        )
    )


def build_task_request(session_id: str, payload: bytes) -> bytes:
    return encode_message(
        ProtocolMessage(
            msg_type=MessageType.FULL_CLIENT_REQUEST,
            flag=MessageFlag.WITH_EVENT,
            event=EventType.TASK_REQUEST,
            session_id=session_id,
            payload=payload,
        )
    )


def build_finish_session(session_id: str) -> bytes:
    return encode_message(
        ProtocolMessage(
            msg_type=MessageType.FULL_CLIENT_REQUEST,
            flag=MessageFlag.WITH_EVENT,
            event=EventType.FINISH_SESSION,
            session_id=session_id,
            payload=b"{}",
        )
    )


def build_finish_connection() -> bytes:
    return encode_message(
        ProtocolMessage(
            msg_type=MessageType.FULL_CLIENT_REQUEST,
            flag=MessageFlag.WITH_EVENT,
            event=EventType.FINISH_CONNECTION,
            payload=b"{}",
        )
    )

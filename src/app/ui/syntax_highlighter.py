from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument


class CFamilySyntaxHighlighter(QSyntaxHighlighter):
    _STATE_BLOCK_COMMENT = 1
    _STATE_VERBATIM_STRING = 2

    _COMMON_KEYWORDS = {
        "auto",
        "break",
        "case",
        "char",
        "const",
        "continue",
        "default",
        "do",
        "double",
        "else",
        "enum",
        "extern",
        "float",
        "for",
        "goto",
        "if",
        "inline",
        "int",
        "long",
        "register",
        "return",
        "short",
        "signed",
        "sizeof",
        "static",
        "struct",
        "switch",
        "typedef",
        "union",
        "unsigned",
        "void",
        "volatile",
        "while",
    }

    _CPP_KEYWORDS = {
        "alignas",
        "alignof",
        "and",
        "and_eq",
        "asm",
        "bitand",
        "bitor",
        "bool",
        "catch",
        "char8_t",
        "char16_t",
        "char32_t",
        "class",
        "compl",
        "concept",
        "const_cast",
        "consteval",
        "constexpr",
        "constinit",
        "co_await",
        "co_return",
        "co_yield",
        "decltype",
        "delete",
        "dynamic_cast",
        "explicit",
        "export",
        "false",
        "friend",
        "mutable",
        "namespace",
        "new",
        "noexcept",
        "not",
        "not_eq",
        "nullptr",
        "operator",
        "or",
        "or_eq",
        "private",
        "protected",
        "public",
        "reinterpret_cast",
        "requires",
        "static_assert",
        "static_cast",
        "template",
        "this",
        "thread_local",
        "throw",
        "true",
        "try",
        "typeid",
        "typename",
        "using",
        "virtual",
        "wchar_t",
        "xor",
        "xor_eq",
    }

    _CSHARP_KEYWORDS = {
        "abstract",
        "as",
        "base",
        "bool",
        "byte",
        "case",
        "catch",
        "char",
        "checked",
        "class",
        "const",
        "continue",
        "decimal",
        "default",
        "delegate",
        "do",
        "double",
        "else",
        "enum",
        "event",
        "explicit",
        "extern",
        "false",
        "finally",
        "fixed",
        "float",
        "for",
        "foreach",
        "goto",
        "if",
        "implicit",
        "in",
        "int",
        "interface",
        "internal",
        "is",
        "lock",
        "long",
        "namespace",
        "new",
        "null",
        "object",
        "operator",
        "out",
        "override",
        "params",
        "private",
        "protected",
        "public",
        "readonly",
        "ref",
        "return",
        "sbyte",
        "sealed",
        "short",
        "sizeof",
        "stackalloc",
        "static",
        "string",
        "struct",
        "switch",
        "this",
        "throw",
        "true",
        "try",
        "typeof",
        "uint",
        "ulong",
        "unchecked",
        "unsafe",
        "ushort",
        "using",
        "var",
        "virtual",
        "void",
        "volatile",
        "while",
        "when",
        "where",
        "yield",
    }

    _COMMON_TYPES = {
        "bool",
        "char",
        "double",
        "float",
        "int",
        "long",
        "short",
        "void",
        "wchar_t",
    }

    _CPP_TYPES = {
        "char8_t",
        "char16_t",
        "char32_t",
        "nullptr_t",
        "size_t",
    }

    _CSHARP_TYPES = {
        "byte",
        "decimal",
        "dynamic",
        "object",
        "sbyte",
        "string",
        "uint",
        "ulong",
        "ushort",
        "nint",
        "nuint",
    }

    _LITERAL_IDENTIFIERS = {"false", "true", "null", "nullptr", "NULL"}

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._theme_mode = "light"
        self._language = "c"
        self._keywords = self._build_keywords("c")
        self._types = self._build_types("c")
        self._formats: dict[str, QTextCharFormat] = {}
        self.set_theme("light")

    def set_theme(self, theme_mode: str) -> None:
        normalized = str(theme_mode).lower()
        if normalized not in {"light", "dark"}:
            normalized = "light"
        if normalized == self._theme_mode and self._formats:
            return

        self._theme_mode = normalized
        colors = self._theme_colors()
        self._formats = {
            "comment": self._make_format(colors["comment"], italic=True),
            "constant": self._make_format(colors["constant"]),
            "function": self._make_format(colors["function"]),
            "keyword": self._make_format(colors["keyword"], bold=True),
            "number": self._make_format(colors["number"]),
            "preprocessor": self._make_format(colors["preprocessor"], bold=True),
            "string": self._make_format(colors["string"]),
            "char": self._make_format(colors["char"]),
            "type": self._make_format(colors["type"], bold=True),
        }
        self.rehighlight()

    def set_language(self, language: str) -> None:
        normalized = str(language).lower()
        if normalized not in {"c", "cpp", "csharp"}:
            normalized = "c"
        if normalized == self._language and self._keywords:
            return

        self._language = normalized
        self._keywords = self._build_keywords(normalized)
        self._types = self._build_types(normalized)
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        if not text:
            self.setCurrentBlockState(0)
            return

        if self.previousBlockState() == self._STATE_VERBATIM_STRING:
            end_index = self._find_verbatim_string_end(text, 0)
            if end_index == -1:
                self.setFormat(0, len(text), self._formats["string"])
                self.setCurrentBlockState(self._STATE_VERBATIM_STRING)
                return

            self.setFormat(0, end_index, self._formats["string"])
            index = end_index
        elif self.previousBlockState() == self._STATE_BLOCK_COMMENT:
            end_index = text.find("*/")
            if end_index == -1:
                self.setFormat(0, len(text), self._formats["comment"])
                self.setCurrentBlockState(self._STATE_BLOCK_COMMENT)
                return

            self.setFormat(0, end_index + 2, self._formats["comment"])
            index = end_index + 2
        else:
            index = 0

        self.setCurrentBlockState(0)

        if text.lstrip().startswith("#"):
            self.setFormat(0, len(text), self._formats["preprocessor"])
            return

        length = len(text)
        while index < length:
            if text.startswith("//", index):
                self.setFormat(index, length - index, self._formats["comment"])
                break

            if text.startswith("/*", index):
                end_index = text.find("*/", index + 2)
                if end_index == -1:
                    self.setFormat(index, length - index, self._formats["comment"])
                    self.setCurrentBlockState(self._STATE_BLOCK_COMMENT)
                    return

                self.setFormat(index, end_index + 2 - index, self._formats["comment"])
                index = end_index + 2
                continue

            string_span = self._consume_string(text, index)
            if string_span is not None:
                end_index, is_verbatim = string_span
                if end_index == -1:
                    self.setFormat(index, length - index, self._formats["string"])
                    if is_verbatim:
                        self.setCurrentBlockState(self._STATE_VERBATIM_STRING)
                    return

                self.setFormat(index, end_index - index, self._formats["string"])
                index = end_index
                if is_verbatim and end_index < length:
                    continue
                continue

            char = text[index]
            if char == "@" and index + 1 < length and self._is_identifier_start(text[index + 1]):
                start = index + 1
                index = start + 1
                while index < length and self._is_identifier_part(text[index]):
                    index += 1
                word = text[start:index]
                if word in self._LITERAL_IDENTIFIERS or (word.isupper() and len(word) > 1 and "_" in word):
                    self.setFormat(start, index - start, self._formats["constant"])
                elif word in self._types:
                    self.setFormat(start, index - start, self._formats["type"])
                elif word in self._keywords:
                    self.setFormat(start, index - start, self._formats["keyword"])
                elif self._looks_like_function_call(text, index):
                    self.setFormat(start, index - start, self._formats["function"])
                continue

            if self._is_identifier_start(char):
                start = index
                index += 1
                while index < length and self._is_identifier_part(text[index]):
                    index += 1
                word = text[start:index]
                if word in self._LITERAL_IDENTIFIERS or (word.isupper() and len(word) > 1 and "_" in word):
                    self.setFormat(start, index - start, self._formats["constant"])
                elif word in self._types:
                    self.setFormat(start, index - start, self._formats["type"])
                elif word in self._keywords:
                    self.setFormat(start, index - start, self._formats["keyword"])
                elif self._looks_like_function_call(text, index):
                    self.setFormat(start, index - start, self._formats["function"])
                continue

            if char.isdigit():
                start = index
                index += 1
                while index < length and (text[index].isalnum() or text[index] in "._xXbB'"):
                    index += 1
                self.setFormat(start, index - start, self._formats["number"])
                continue

            index += 1

    def _consume_string(self, text: str, index: int) -> tuple[int, bool] | None:
        length = len(text)

        if text.startswith("u8", index) and index + 2 < length and text[index + 2] in {'"', "'"}:
            end_index = self._consume_escaped_string(text, index + 2)
            return end_index, False

        if text[index] in {"u", "U", "L"} and index + 1 < length and text[index + 1] in {'"', "'"}:
            end_index = self._consume_escaped_string(text, index + 1)
            return end_index, False

        prefix_index = index
        while prefix_index < length and text[prefix_index] in {"@", "$"}:
            prefix_index += 1
        if prefix_index > index and prefix_index < length and text[prefix_index] == '"':
            end_index = self._find_verbatim_string_end(text, prefix_index + 1)
            return end_index, True

        if text[index] in {'"', "'"}:
            end_index = self._consume_escaped_string(text, index)
            return end_index, False

        return None

    def _consume_escaped_string(self, text: str, quote_index: int) -> int:
        quote_char = text[quote_index]
        index = quote_index + 1
        escaped = False
        while index < len(text):
            current = text[index]
            if escaped:
                escaped = False
            elif current == "\\":
                escaped = True
            elif current == quote_char:
                return index + 1
            index += 1
        return -1

    def _find_verbatim_string_end(self, text: str, start_index: int) -> int:
        index = start_index
        while index < len(text):
            current = text[index]
            if current == '"':
                if index + 1 < len(text) and text[index + 1] == '"':
                    index += 2
                    continue
                return index + 1
            index += 1
        return -1

    def _looks_like_function_call(self, text: str, index: int) -> bool:
        next_index = index
        length = len(text)
        while next_index < length and text[next_index].isspace():
            next_index += 1
        if next_index >= length or text[next_index] != "(":
            return False

        previous_index = index - 1
        while previous_index >= 0 and text[previous_index].isspace():
            previous_index -= 1
        if previous_index >= 0 and text[previous_index] in {".", ":", ">"}:
            return False
        return True

    def _is_identifier_start(self, character: str) -> bool:
        return character == "_" or character.isalpha()

    def _is_identifier_part(self, character: str) -> bool:
        return character == "_" or character.isalnum()

    def _build_keywords(self, language: str) -> set[str]:
        keywords = set(self._COMMON_KEYWORDS)
        if language == "cpp":
            keywords.update(self._CPP_KEYWORDS)
        elif language == "csharp":
            keywords.update(self._CSHARP_KEYWORDS)
        return keywords

    def _build_types(self, language: str) -> set[str]:
        types = set(self._COMMON_TYPES)
        if language == "cpp":
            types.update(self._CPP_TYPES)
        elif language == "csharp":
            types.update(self._CSHARP_TYPES)
        return types

    def _make_format(self, color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
        text_format = QTextCharFormat()
        text_format.setForeground(QColor(color))
        if bold:
            text_format.setFontWeight(QFont.Weight.Bold)
        if italic:
            text_format.setFontItalic(True)
        return text_format

    def _theme_colors(self) -> dict[str, str]:
        if self._theme_mode == "dark":
            return {
                "comment": "#6a9955",
                "constant": "#4fc1ff",
                "function": "#dcdcaa",
                "keyword": "#569cd6",
                "number": "#b5cea8",
                "preprocessor": "#c586c0",
                "string": "#ce9178",
                "char": "#ce9178",
                "type": "#4ec9b0",
            }
        return {
            "comment": "#008000",
            "constant": "#0057b8",
            "function": "#795e26",
            "keyword": "#0b5cad",
            "number": "#b05a00",
            "preprocessor": "#8a3b00",
            "string": "#a31515",
            "char": "#a31515",
            "type": "#0f766e",
        }
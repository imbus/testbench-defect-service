import re
from enum import Enum

from bs4 import BeautifulSoup, NavigableString


class _HtmlToJiraConverter:
    """Converts HTML to Jira wiki markup."""

    class Emoticons(Enum):
        smile = ":)"
        sad = ":("
        tongue = ":P"
        biggrin = ":D"
        wink = ";)"
        thumbs_up = "(y)"
        thumbs_down = "(n)"
        information = "(i)"
        check = "(/)"
        error = "(x)"
        warning = "(!)"
        forbidden = "(-)"
        add = "(+)"
        help_16 = "(?)"
        lightbulb_on = "(on)"
        lightbulb = "(off)"
        star_yellow = "(*y)"
        star_red = "(*r)"
        star_green = "(*g)"
        star_blue = "(*b)"
        flag = "(flag)"

    def convert(self, html_content: str) -> str:
        if not html_content:
            return ""
        soup = BeautifulSoup(html_content, "html.parser")
        result = self._process_node(soup)
        return re.sub(r"\n{3,}", "\n\n", result).strip()

    def _process_node(self, tag) -> str:
        markup = ""
        for child in tag.children:
            if isinstance(child, NavigableString):
                markup += str(child)
            else:
                markup += self._dispatch(child)
        return markup

    def _dispatch(self, tag) -> str:
        handlers = {
            "h1": self._heading,
            "h2": self._heading,
            "h3": self._heading,
            "h4": self._heading,
            "h5": self._heading,
            "h6": self._heading,
            "b": self._bold,
            "strong": self._bold,
            "i": self._italic,
            "em": self._italic,
            "cite": self._cite,
            "ins": self._underline,
            "u": self._underline,
            "del": self._strikethrough,
            "s": self._strikethrough,
            "strike": self._strikethrough,
            "tt": self._monospace,
            "code": self._monospace,
            "sub": self._subscript,
            "sup": self._superscript,
            "font": self._font,
            "br": self._line_break,
            "p": self._paragraph,
            "blockquote": self._blockquote,
            "ul": self._list,
            "ol": self._list,
            "hr": self._horizontal_rule,
            "img": self._image,
            "table": self._table,
            "a": self._link,
            "div": self._div,
            "span": self._span,
        }
        handler = handlers.get(tag.name)
        if handler:
            return handler(tag)
        return self._process_node(tag)

    def _heading(self, tag) -> str:
        return f"\n{tag.name}. {self._process_node(tag).strip()}\n"

    def _bold(self, tag) -> str:
        return f"*{self._process_node(tag)}*"

    def _italic(self, tag) -> str:
        return f"_{self._process_node(tag)}_"

    def _cite(self, tag) -> str:
        return f"??{self._process_node(tag)}??"

    def _underline(self, tag) -> str:
        return f"+{self._process_node(tag)}+"

    def _strikethrough(self, tag) -> str:
        return f"-{self._process_node(tag)}-"

    def _monospace(self, tag) -> str:
        if tag.find_parent("pre"):
            return self._process_node(tag)
        return f"{{{{{self._process_node(tag)}}}}}"

    def _subscript(self, tag) -> str:
        return f"~{self._process_node(tag)}~"

    def _superscript(self, tag) -> str:
        return f"^{self._process_node(tag)}^"

    def _font(self, tag) -> str:
        if tag.has_attr("color"):
            return f"{{color:{tag['color']}}}{self._process_node(tag)}{{color}}"
        return self._process_node(tag)

    def _line_break(self, tag) -> str:
        return "\\\\"

    def _span(self, tag) -> str:
        style = tag.get("style", "")
        classes = tag.get("class", None)
        if "underline" in style:
            return self._underline(tag)
        if "line-through" in style:
            return self._strikethrough(tag)
        if classes:
            emoticon = set(classes) & {str(emoticon.name) for emoticon in self.Emoticons}
            for emote in emoticon:
                return f"{(self.Emoticons[emote].value)} "
        if "image-wrap" in classes:
            if tag.get("data-src", None):
                return f"!{tag.get('data-src', None)}!"
            return self._process_node(tag)

        return self._process_node(tag)

    def _paragraph(self, tag) -> str:
        return f"\n{self._process_node(tag)}\n"

    def _blockquote(self, tag) -> str:
        return f"{{quote}}\n{self._process_node(tag)}\n{{quote}}"

    def _horizontal_rule(self, tag) -> str:
        return "\n----\n"

    def _list(self, tag) -> str:
        return "\n" + self._process_list(tag, "")

    def _process_list(self, list_tag, prefix: str) -> str:
        new_prefix = prefix + ("#" if list_tag.name == "ol" else "*")
        markup = ""
        for li in list_tag.find_all("li", recursive=False):
            inline_markup = ""
            nested_markup = ""
            for child in li.children:
                if isinstance(child, NavigableString):
                    inline_markup += str(child)
                elif child.name in ("ul", "ol"):
                    nested_markup += self._process_list(child, new_prefix)
                else:
                    inline_markup += self._dispatch(child)
            markup += f"{new_prefix} {inline_markup.strip()}\n"
            markup += nested_markup
        return markup

    def _image(self, tag) -> str:
        src = tag.get("src")
        if not src:
            return ""
        props = []
        if width := tag.get("width"):
            props.append(f"width={width}")
        if height := tag.get("height"):
            props.append(f"height={height}")
        if alt := tag.get("alt"):
            props.append(f"alt={alt}")
        prop_str = f"|{','.join(props)}" if props else ""
        return f"!{src}{prop_str}!"

    def _table(self, tag) -> str:
        rows = []
        for row in tag.find_all("tr"):
            is_header = bool(row.find("th"))
            sep = "||" if is_header else "|"
            cells = [self._process_node(c).strip() for c in row.find_all(["td", "th"])]
            if cells:
                rows.append(f"{sep}{sep.join(cells)}{sep}")
        return "\n" + "\n".join(rows) + "\n"

    def _link(self, tag) -> str:
        if tag.has_attr("href"):
            return f"[{self._process_node(tag)}|{tag['href']}]"
        return self._process_node(tag)

    def _div(self, tag) -> str:
        classes = tag.get("class", [])
        if "code" in classes:
            return self._div_code(tag)
        if "preformatted" in classes:
            return self._div_preformatted(tag)
        if "panel" in classes:
            return self._div_panel(tag)
        return self._process_node(tag)

    def _div_code(self, tag) -> str:
        pre = tag.find("pre")
        lang = ""
        if pre:
            code_content = pre.get_text()
            for cls in pre.get("class", []):
                if cls.startswith("code-"):
                    lang = cls[5:]
                    break
        else:
            code_content = ""
        lang_str = f":{lang}" if lang else ""
        return f"\n{{code{lang_str}}}\n{code_content.strip()}\n{{code}}\n"

    def _div_preformatted(self, tag) -> str:
        pre = tag.find("pre")
        pre_content = pre.get_text() if pre else ""
        return f"\n{{noformat}}\n{pre_content.strip()}\n{{noformat}}\n"

    def _parse_css(self, style: str) -> dict:
        css = {}
        for declaration in style.split(";"):
            if ":" in declaration:
                prop, _, value = declaration.partition(":")
                css[prop.strip().lower()] = value.strip()
        return css

    def _div_panel(self, tag) -> str:
        title_div = tag.find("div", class_="panelHeader")
        content_div = tag.find("div", class_="panelContent")

        params = []
        if title_div and (title_text := title_div.get_text().strip()):
            params.append(f"title={title_text}")

        css = self._parse_css(tag.get("style", ""))
        if border_style := css.get("border-style"):
            params.append(f"borderStyle={border_style}")
        if border_color := css.get("border-color"):
            params.append(f"borderColor={border_color}")
        if border_width := css.get("border-width"):
            params.append(f"borderWidth={border_width}")
        if bg_color := css.get("background-color"):
            params.append(f"bgColor={bg_color}")

        if title_div:
            title_css = self._parse_css(title_div.get("style", ""))
            if title_bg_color := title_css.get("background-color"):
                params.append(f"titleBGColor={title_bg_color}")

        param_str = "|".join(params)
        content = self._process_node(content_div) if content_div else ""
        return f"\n{{panel:{param_str}}}\n{content}\n{{panel}}\n"


def convert_html_to_jira_markup(html_content: str) -> str:
    return _HtmlToJiraConverter().convert(html_content)

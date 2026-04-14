"""Unit tests for convert_html_to_jira_markup() in html_to_jira.py."""

import pytest

from testbench_defect_service.clients.jira.html_to_jira import (
    _HtmlToJiraConverter,
    convert_html_to_jira_markup,
)


class TestEdgeCases:
    def test_empty_string_returns_empty(self):
        assert convert_html_to_jira_markup("") == ""

    def test_none_returns_empty(self):
        assert convert_html_to_jira_markup(None) == ""

    def test_plain_text_passthrough(self):
        assert convert_html_to_jira_markup("Hello World") == "Hello World"

    def test_multiple_blank_lines_collapsed(self):
        result = convert_html_to_jira_markup("<p>A</p><p>B</p><p>C</p>")
        assert "\n\n\n" not in result


class TestHeadings:
    @pytest.mark.parametrize("level", range(1, 7))
    def test_heading_levels(self, level):
        html = f"<h{level}>Title</h{level}>"
        result = convert_html_to_jira_markup(html)
        assert f"h{level}. Title" in result

    def test_heading_with_nested_markup(self):
        result = convert_html_to_jira_markup("<h1><b>Bold Title</b></h1>")
        assert "h1. *Bold Title*" in result


class TestTextFormatting:
    def test_bold_b(self):
        assert "*bold*" in convert_html_to_jira_markup("<b>bold</b>")

    def test_bold_strong(self):
        assert "*bold*" in convert_html_to_jira_markup("<strong>bold</strong>")

    def test_italic_i(self):
        assert "_italic_" in convert_html_to_jira_markup("<i>italic</i>")

    def test_italic_em(self):
        assert "_italic_" in convert_html_to_jira_markup("<em>italic</em>")

    def test_cite(self):
        assert "??citation??" in convert_html_to_jira_markup("<cite>citation</cite>")

    def test_underline_ins(self):
        assert "+underline+" in convert_html_to_jira_markup("<ins>underline</ins>")

    def test_underline_u(self):
        assert "+underline+" in convert_html_to_jira_markup("<u>underline</u>")

    def test_underline_span_style(self):
        assert "+underline+" in convert_html_to_jira_markup(
            '<span style="text-decoration: underline;">underline</span>'
        )

    def test_strikethrough_del(self):
        assert "-strike-" in convert_html_to_jira_markup("<del>strike</del>")

    def test_strikethrough_s(self):
        assert "-strike-" in convert_html_to_jira_markup("<s>strike</s>")

    def test_strikethrough_strike(self):
        assert "-strike-" in convert_html_to_jira_markup("<strike>strike</strike>")

    def test_strikethrough_span_style(self):
        assert "-strike-" in convert_html_to_jira_markup(
            '<span style="text-decoration: line-through;">strike</span>'
        )

    def test_monospaced_tt(self):
        assert "{{mono}}" in convert_html_to_jira_markup("<tt>mono</tt>")

    def test_monospaced_code_inline(self):
        assert "{{mono}}" in convert_html_to_jira_markup("<code>mono</code>")

    def test_code_inside_pre_not_monospaced(self):
        """<code> inside <pre> should NOT become {{mono}}."""
        result = convert_html_to_jira_markup("<pre><code>print('hi')</code></pre>")
        assert "{{" not in result

    def test_subscript(self):
        assert "~sub~" in convert_html_to_jira_markup("<sub>sub</sub>")

    def test_superscript(self):
        assert "^sup^" in convert_html_to_jira_markup("<sup>sup</sup>")

    def test_color_hex(self):
        result = convert_html_to_jira_markup('<font color="#ff0000">red</font>')
        assert "{color:#ff0000}red{color}" in result

    def test_color_named(self):
        result = convert_html_to_jira_markup('<font color="red">red</font>')
        assert "{color:red}red{color}" in result

    def test_line_break_br(self):
        result = convert_html_to_jira_markup("before<br>after")
        assert "\\\\" in result

    def test_combined_bold_italic(self):
        result = convert_html_to_jira_markup("<b><i>bold-italic</i></b>")
        assert "*_bold-italic_*" in result


class TestBlockElements:
    def test_paragraph(self):
        result = convert_html_to_jira_markup("<p>Hello</p>")
        assert "Hello" in result

    def test_blockquote(self):
        result = convert_html_to_jira_markup("<blockquote>quoted</blockquote>")
        assert "{quote}" in result
        assert "quoted" in result

    def test_horizontal_rule(self):
        result = convert_html_to_jira_markup("<hr>")
        assert "----" in result


class TestLists:
    def test_unordered_list(self):
        result = convert_html_to_jira_markup("<ul><li>Item A</li><li>Item B</li></ul>")
        assert "* Item A" in result
        assert "* Item B" in result

    def test_ordered_list(self):
        result = convert_html_to_jira_markup("<ol><li>First</li><li>Second</li></ol>")
        assert "# First" in result
        assert "# Second" in result

    def test_nested_unordered_list(self):
        html = "<ul><li>Top<ul><li>Nested</li></ul></li></ul>"
        result = convert_html_to_jira_markup(html)
        assert "* Top" in result
        assert "** Nested" in result

    def test_nested_ordered_list(self):
        html = "<ol><li>Top<ol><li>Nested</li></ol></li></ol>"
        result = convert_html_to_jira_markup(html)
        assert "# Top" in result
        assert "## Nested" in result

    def test_mixed_nested_list_ul_in_ol(self):
        html = "<ol><li>Top<ul><li>Bullet</li></ul></li></ol>"
        result = convert_html_to_jira_markup(html)
        assert "# Top" in result
        assert "#* Bullet" in result

    def test_mixed_nested_list_ol_in_ul(self):
        html = "<ul><li>Top<ol><li>Number</li></ol></li></ul>"
        result = convert_html_to_jira_markup(html)
        assert "* Top" in result
        assert "*# Number" in result


class TestImage:
    def test_image_simple(self):
        result = convert_html_to_jira_markup('<img src="pic.png">')
        assert "!pic.png!" in result

    def test_image_with_dimensions(self):
        result = convert_html_to_jira_markup('<img src="pic.png" width="100" height="50">')
        assert "!pic.png|" in result
        assert "width=100" in result
        assert "height=50" in result

    def test_image_with_alt(self):
        result = convert_html_to_jira_markup('<img src="pic.png" alt="description">')
        assert "alt=description" in result

    def test_image_without_src_ignored(self):
        result = convert_html_to_jira_markup('<img alt="no src">')
        assert "!" not in result


class TestTable:
    def test_table_with_headers(self):
        html = "<table><tr><th>H1</th><th>H2</th></tr><tr><td>A</td><td>B</td></tr></table>"
        result = convert_html_to_jira_markup(html)
        assert "||H1||H2||" in result
        assert "|A|B|" in result

    def test_table_without_headers(self):
        html = "<table><tr><td>A</td><td>B</td></tr></table>"
        result = convert_html_to_jira_markup(html)
        assert "|A|B|" in result
        assert "||" not in result

    def test_table_single_cell(self):
        result = convert_html_to_jira_markup("<table><tr><td>Only</td></tr></table>")
        assert "|Only|" in result


class TestCodeBlocks:
    def test_code_div(self):
        html = '<div class="code"><pre>print("hello")</pre></div>'
        result = convert_html_to_jira_markup(html)
        assert "{code}" in result
        assert 'print("hello")' in result

    def test_code_div_with_language(self):
        html = '<div class="code"><pre class="code-python">print("hello")</pre></div>'
        result = convert_html_to_jira_markup(html)
        assert "{code:python}" in result

    def test_code_div_java_language(self):
        html = '<div class="code"><pre class="code-java">int x = 1;</pre></div>'
        result = convert_html_to_jira_markup(html)
        assert "{code:java}" in result

    def test_preformatted_div(self):
        html = '<div class="preformatted"><pre>raw text</pre></div>'
        result = convert_html_to_jira_markup(html)
        assert "{noformat}" in result
        assert "raw text" in result

    def test_preformatted_opening_and_closing(self):
        html = '<div class="preformatted"><pre>data</pre></div>'
        result = convert_html_to_jira_markup(html)
        assert result.count("{noformat}") == 2


class TestPanel:
    def test_panel_with_title(self):
        html = (
            '<div class="panel">'
            '<div class="panelHeader">My Title</div>'
            '<div class="panelContent">Content here</div>'
            "</div>"
        )
        result = convert_html_to_jira_markup(html)
        assert "{panel:title=My Title}" in result
        assert "Content here" in result
        assert "{panel}" in result

    def test_panel_without_title(self):
        html = '<div class="panel"><div class="panelContent">Content</div></div>'
        result = convert_html_to_jira_markup(html)
        assert "{panel:" in result
        assert "Content" in result


class TestLinks:
    def test_link_with_text(self):
        result = convert_html_to_jira_markup('<a href="https://example.com">Example</a>')
        assert "[Example|https://example.com]" in result

    def test_link_with_nested_markup(self):
        result = convert_html_to_jira_markup('<a href="https://example.com"><b>Bold</b></a>')
        assert "[*Bold*|https://example.com]" in result

    def test_anchor_without_href_rendered_as_text(self):
        """<a> without href should just render its text content."""
        result = convert_html_to_jira_markup('<a name="anchor">Anchor</a>')
        assert "[" not in result
        assert "Anchor" in result


class TestIntegration:
    def test_full_document(self):
        html = (
            "<h1>Title</h1>"
            "<p>Normal <b>bold</b> and <i>italic</i> text.</p>"
            "<ul><li>Item 1</li><li>Item 2</li></ul>"
            '<a href="https://example.com">Link</a>'
        )
        result = convert_html_to_jira_markup(html)
        assert "h1. Title" in result
        assert "*bold*" in result
        assert "_italic_" in result
        assert "* Item 1" in result
        assert "[Link|https://example.com]" in result

    def test_color_with_nested_bold(self):
        html = '<font color="blue"><b>colored bold</b></font>'
        result = convert_html_to_jira_markup(html)
        assert "{color:blue}" in result
        assert "*colored bold*" in result

    def test_subscript_with_color(self):
        result = convert_html_to_jira_markup('<sub><font color="red">low</font></sub>')
        assert "~" in result
        assert "{color:red}" in result


class TestConverterClass:
    """Tests that exercise _HtmlToJiraConverter directly."""

    def setup_method(self):
        self.converter = _HtmlToJiraConverter()

    def test_convert_empty_returns_empty(self):
        assert self.converter.convert("") == ""

    def test_convert_none_returns_empty(self):
        assert self.converter.convert(None) == ""

    def test_convert_result_matches_module_function(self):
        html = "<h1>Title</h1><p><b>bold</b></p>"
        assert self.converter.convert(html) == convert_html_to_jira_markup(html)

    def test_unknown_tag_renders_children(self):
        """Unknown tags should fall through and render their text content."""
        result = convert_html_to_jira_markup("<article>some text</article>")
        assert "some text" in result

    def test_font_without_color_renders_children(self):
        result = convert_html_to_jira_markup("<font>plain</font>")
        assert "plain" in result
        assert "{color" not in result

    def test_span_without_style_renders_children(self):
        result = convert_html_to_jira_markup('<span class="highlight">text</span>')
        assert "text" in result
        assert "+" not in result
        assert "-text-" not in result

    def test_div_without_special_class_renders_children(self):
        result = convert_html_to_jira_markup('<div class="wrapper">content</div>')
        assert "content" in result

    def test_anchor_without_href_renders_text(self):
        result = convert_html_to_jira_markup('<a name="top">Back to top</a>')
        assert "Back to top" in result
        assert "[" not in result


class TestSpanFormatting:
    def test_span_underline_style(self):
        result = convert_html_to_jira_markup('<span style="text-decoration: underline;">u</span>')
        assert "+u+" in result

    def test_span_line_through_style(self):
        result = convert_html_to_jira_markup(
            '<span style="text-decoration: line-through;">s</span>'
        )
        assert "-s-" in result

    def test_span_both_styles_prefers_underline(self):
        """When both underline and line-through appear, underline is checked first."""
        result = convert_html_to_jira_markup(
            '<span style="text-decoration: underline line-through;">x</span>'
        )
        assert "+x+" in result


class TestDivVariants:
    def test_code_div_without_pre_produces_empty_code_block(self):
        html = '<div class="code"></div>'
        result = convert_html_to_jira_markup(html)
        assert "{code}" in result

    def test_preformatted_div_without_pre_produces_empty_noformat(self):
        html = '<div class="preformatted"></div>'
        result = convert_html_to_jira_markup(html)
        assert "{noformat}" in result

    def test_panel_without_content_div(self):
        html = '<div class="panel"><div class="panelHeader">Title</div></div>'
        result = convert_html_to_jira_markup(html)
        assert "{panel:title=Title}" in result
        assert "{panel}" in result

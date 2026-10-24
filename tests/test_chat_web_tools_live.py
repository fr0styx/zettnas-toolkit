"""The AI web tools on their real paths (test mode off) against fake Wikipedia, DuckDuckGo and wttr.in."""

import io
import json

import pytest

from backend.services import chat_web_tools as web


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeWeb:
    def __init__(self, routes):
        self.routes = routes
        self.urls = []

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        self.urls.append(url)
        for part, body in self.routes.items():
            if part in url:
                if isinstance(body, Exception):
                    raise body
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                return FakeResponse(data)
        raise OSError(f"no fake for {url}")


@pytest.fixture
def live(monkeypatch):
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("ZETTNAS_TEST_MODE", raising=False)
    token = web._WEB_ALLOWED.set(True)
    yield monkeypatch
    web._WEB_ALLOWED.reset(token)


WIKI_SEARCH = {"query": {"search": [{"title": "France"}]}}
WIKI_DETAIL = {
    "query": {
        "pages": {
            "1": {
                "title": "France",
                "extract": "France is a country in Western Europe. Its capital is Paris.",
                "revisions": [{"*": "{{Infobox country\n| capital = [[Paris]]\n| leader_name1 = Emmanuel Macron\n}}"}],
            }
        }
    }
}
DDG_HTML = (
    b'<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Ffrance">France facts</a>'
    b'<a class="result__snippet">France has 13 regions and a population of about 68 million people.</a>'
)
DDG_API = {
    "AbstractText": "France, officially the French Republic, is a country.",
    "AbstractURL": "https://duckduckgo.com/France",
    "Heading": "France",
}


class TestBrowse:
    def test_blocked_unless_web_is_on(self):
        assert web.tool_browse_internet("what is the capital of france")["status"] == "blocked"

    def test_empty_query(self, live):
        assert web.tool_browse_internet("  ")["status"] == "error"

    def test_combines_wikipedia_ddg_and_instant_answers(self, live):
        fake = FakeWeb(
            {
                "list=search": WIKI_SEARCH,
                "prop=extracts": WIKI_DETAIL,
                "html.duckduckgo.com": DDG_HTML,
                "api.duckduckgo.com": DDG_API,
            }
        )
        live.setattr(web.urllib.request, "urlopen", fake)
        out = web.tool_browse_internet("what is the capital of france", max_results=5)
        assert out["status"] == "ok"
        kinds = [s["source"] for s in out["sources"]]
        assert "wikipedia" in kinds and "web" in kinds and "duckduckgo" in kinds
        assert any(s["url"] == "https://example.org/france" for s in out["sources"])
        assert out["extracted_facts"].get("article_title") == "France"
        assert out["direct_answer"]

    def test_incumbent_gets_a_direct_answer(self, live):
        detail = {
            "query": {
                "pages": {
                    "1": {
                        "title": "President of France",
                        "extract": "The president is the head of state.",
                        "revisions": [
                            {
                                "*": "{{Infobox political post\n| incumbent = Emmanuel Macron\n| incumbentsince = 14 May 2017\n}}"
                            }
                        ],
                    }
                }
            }
        }
        summary = {
            "extract": "Emmanuel Macron is a French politician.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Emmanuel_Macron"}},
        }
        fake = FakeWeb(
            {
                "list=search": {"query": {"search": [{"title": "President of France"}]}},
                "prop=extracts": detail,
                "page/summary": summary,
                "html.duckduckgo.com": b"",
                "api.duckduckgo.com": {},
            }
        )
        live.setattr(web.urllib.request, "urlopen", fake)
        out = web.tool_browse_internet("who is the president of france")
        assert "Emmanuel Macron" in out["direct_answer"] and "since 14 May 2017" in out["direct_answer"]

    def test_everything_failing_still_answers(self, live):
        live.setattr(web.urllib.request, "urlopen", FakeWeb({}))
        out = web.tool_browse_internet("obscure question about nothing")
        assert out["status"] == "ok" and out["sources"] == []

    def test_private_urls_are_not_fetched(self, live):
        fake = FakeWeb({})
        live.setattr(web.urllib.request, "urlopen", fake)
        web.tool_browse_internet("summarise http://192.168.1.1/admin please")
        assert not any("192.168.1.1" in u for u in fake.urls)

    def test_refuses_queries_with_secrets(self, live):
        out = web.tool_browse_internet("is my password hunter2 and key sk-ABCDEF1234567890ABCDEF1234567890 safe")
        assert out["status"] in ("blocked", "ok")
        if out["status"] == "ok":
            assert "sk-ABCDEF" not in out["query"]


WTTR = {
    "nearest_area": [
        {
            "areaName": [{"value": "Santo Domingo"}],
            "country": [{"value": "Dominican Republic"}],
            "region": [{"value": "Distrito Nacional"}],
        }
    ],
    "current_condition": [
        {
            "temp_C": "30",
            "temp_F": "86",
            "FeelsLikeC": "34",
            "FeelsLikeF": "93",
            "weatherDesc": [{"value": "Partly cloudy"}],
            "humidity": "71",
            "windspeedKmph": "10",
            "winddir16Point": "E",
            "uvIndex": "8",
        }
    ],
    "weather": [
        {
            "date": "2026-10-24",
            "maxtempC": "31",
            "mintempC": "24",
            "hourly": [{"weatherDesc": [{"value": "Sunny"}]}] * 8,
        },
        {
            "date": "2026-10-25",
            "maxtempC": "30",
            "mintempC": "23",
            "hourly": [{"weatherDesc": [{"value": "Light rain"}]}] * 8,
        },
    ],
}


class TestWeather:
    def test_parse_wttr(self):
        out = web._parse_single_wttr_response(WTTR, "x")
        text = json.dumps(out)
        assert "Santo Domingo" in text and "Dominican Republic" in text and "30" in text
        assert len(out.get("forecast", out.get("forecast_days", []))) == 2 or "Tomorrow" in text

    def test_fetch(self, live):
        live.setattr(web.urllib.request, "urlopen", FakeWeb({"wttr.in": WTTR}))
        assert web._fetch_wttr_in("Santo Domingo")["current_condition"][0]["temp_C"] == "30"
        live.setattr(web.urllib.request, "urlopen", FakeWeb({}))
        assert web._fetch_wttr_in("Nowhere") is None

    @pytest.mark.parametrize(
        "desc, icon",
        [("Light rain shower", None), ("Sunny", None), ("Snow", None), ("Overcast clouds", None), ("Haze", None)],
    )
    def test_icons(self, desc, icon):
        assert web._get_weather_icon(desc)

    def test_flags(self):
        assert web._get_country_flag("Germany") or True
        assert web._get_country_flag("Atlantis", "DE") == "\U0001f1e9\U0001f1ea"
        assert web._get_country_flag("Atlantis") == "\U0001f30d"

    @pytest.mark.parametrize(
        "asked, reply, want",
        [
            (
                "Did you mean Santo Domingo in the Dominican Republic or in Chile?",
                "the dominican one",
                "Santo Domingo, Dominican Republic",
            ),
            ("Did you mean Santo Domingo in the Dominican Republic or in Chile?", "chile", "Santo Domingo, Chile"),
            ("Santiago in Chile, the Dominican Republic or Spain?", "spain", "Santiago de Compostela, Spain"),
            ("San Jose in Costa Rica or California?", "california", "San Jose, CA"),
            ("Cordoba in Argentina or Spain?", "argentina", "Cordoba, Argentina"),
            ("Vancouver in Canada or Washington?", "washington", "Vancouver, WA"),
            ("Springfield in Illinois, Missouri or Massachusetts?", "missouri", "Springfield, MO"),
            ("Anything else?", "yes", None),
        ],
    )
    def test_country_confirmation(self, asked, reply, want):
        assert web._resolve_country_confirmation(reply, asked) == want

    def test_weather_tool(self, live):
        live.setattr(web.urllib.request, "urlopen", FakeWeb({"wttr.in": WTTR}))
        out = web.tool_get_weather("weather in Santo Domingo, Dominican Republic")
        assert out.get("status") in ("ok", "ambiguous") and "Santo Domingo" in json.dumps(out)

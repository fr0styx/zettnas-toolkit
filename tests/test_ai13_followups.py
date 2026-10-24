"""AI-13: follow-up questions search with the topic of the question before."""

from backend.services.ai_chat_agent import rewrite_followup_for_search

H = [{"role": "user", "content": "When is the boiler service due?"}, {"role": "assistant", "content": "Every October."}]


def test_short_follow_ups_carry_the_previous_topic():
    assert rewrite_followup_for_search("and the warranty?", H) == "When is the boiler service due? and the warranty?"
    assert rewrite_followup_for_search("who did it last time?", H).startswith("When is the boiler service due?")
    de = [{"role": "user", "content": "Wann ist die Inspektion beim Golf fällig?"}]
    assert rewrite_followup_for_search("und der TÜV?", de).startswith("Wann ist die Inspektion")
    zh = [{"role": "user", "content": "空调多久清洗一次？"}]
    assert rewrite_followup_for_search("那保修呢？", zh).startswith("空调多久清洗一次")


def test_new_questions_stay_as_they_are():
    q = "How much did the car insurance cost in February this year?"
    assert rewrite_followup_for_search(q, H) == q
    assert rewrite_followup_for_search("and the warranty?", None) == "and the warranty?"

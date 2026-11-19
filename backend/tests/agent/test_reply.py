import pytest

from app.agent.reply import dedupe_questions

LIVE_RUN = (
    "Friday bugünkü Linear Algebra dersini iptal etti.\n"
    "Karen: Spora gidemeyeceğin akşam hangi gün? Yarın Salı mı, yoksa Perşembe 26 Kasım mı? "
    "Söylersen hemen iptal edeyim.\n"
    "Karen olarak sormak istiyorum: Spora gidemeyeceğin akşam hangi gün — yarın Salı mı, "
    "yoksa Perşembe 26 Kasım mı? Söylediğin günü hemen iptal edeyim."
)


def test_the_repeated_question_from_the_live_run_is_dropped() -> None:
    result = dedupe_questions(LIVE_RUN)

    assert result.count("hangi gün") == 1
    assert "Karen olarak sormak istiyorum" not in result
    assert "Friday bugünkü Linear Algebra dersini iptal etti." in result
    assert "Söylediğin günü hemen iptal edeyim." in result  # statements are kept


@pytest.mark.parametrize(
    "text",
    [
        "EE211 için devamsızlık sınırın kaç? MATH221 için devamsızlık sınırın kaç?",
        "Spor salı mı iptal edilsin, perşembe mi? Linear salı mı iptal edilsin, perşembe mi?",
        "20 Kasım Cuma mı? 27 Kasım Cuma mı?",
        "Yarın, 24 Kasım Salı:\n- 14:00 Iceberg toplantısı\n- 19:00-20:00 Spor",
        "Kaydettim. Başka bir şey var mı?",
    ],
)
def test_different_questions_and_plain_text_are_untouched(text: str) -> None:
    assert dedupe_questions(text) == text


def test_word_for_word_repeat_is_dropped_even_when_short() -> None:
    assert dedupe_questions("Hangi gün?\nJarvis: Hangi gün?") == "Hangi gün?"

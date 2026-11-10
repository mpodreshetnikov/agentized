# NAV — карта Project Context

Один экран. Читай это первым после указателя в корневом `AGENTS.md`. Дальше — только ссылки отсюда.

## Где что

| Раздел | Путь | Назначение |
|--------|------|------------|
| Задачи (живая доска) | [`tasks/INDEX.md`](tasks/INDEX.md) | Активная работа: open / in-progress / blocked |
| Шаблон задачи | [`tasks/TEMPLATE.md`](tasks/TEMPLATE.md) | Поля статуса, родителя, Progress |
| Решения | [`decisions/`](decisions/) | ADR / решения в силе |
| Цели | [`goals/`](goals/) | Цели и приоритеты |
| Path leases | [`leases/INDEX.md`](leases/INDEX.md) | Кто держит какие пути |
| Дайджесты | [`digests/`](digests/) | development / management / releases / architecture |
| Skills (pinned) | [`skills/`](skills/) | Закреплённая копия — позже |
| Hooks (pinned) | [`hooks/`](hooks/) | Закреплённая копия — позже |

## Как искать задачи

1. Открой живой индекс [`tasks/INDEX.md`](tasks/INDEX.md) (только open / in-progress / blocked).
2. Дополнительно — **grep** по id, title, tags в файлах задач.
3. **Запрещено** обходить весь каталог `tasks/` листингом и читать «всю историю» как единственный вход. Полный архив done/dropped — не точка навигации v1.

## Подзадачи

Отдельные файлы рядом с родителем; один уровень вложенности; в файле ребёнка — ссылка на родителя. Claim / доска / leases — на детях. Не выдумывай бэклог: в skeleton нет реальных задач.

## Два режима размещения Context

1. **Вложенный каталог** (этот репозиторий): `context/` внутри code-репо — текущий режим dogfooding.
2. **Отдельный git-репозиторий** Context: тот же каркас (`NAV.md`, `tasks/`, …) живёт в своём репо; code-репо указывает на него через блок в корневом `AGENTS.md`. Отдельный репо здесь **не создаём** — только описываем режим.

Канон: [`docs/target-architecture.md`](../docs/target-architecture.md) (§4.1, §6, §11).

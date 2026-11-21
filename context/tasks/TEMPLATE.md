# T-YYMMDD-xxx — краткий title

статус: open
теги: пример
родитель: _(пусто для корневой задачи; для подзадачи — путь или id родителя)_
claim: _(пусто или кто ведёт)_

Ценность: _(одна фраза простым языком — зачем это людям / бизнесу)_

## Цель

Что должно быть сделано.

## Progress

_(append-only)_

## Decision Log

_(append-only)_

---

Правила (см. NAV и канон §4.2):

- lifecycle: `idea → open|queue → in-progress → self-review|for-review|blocked → done | canceled`
- статус — поле в начале файла; при смене статуса файл не двигается
- **hard gates:** `blocked` → `blocked_reason` + `blocked_deadline` (YYYY-MM-DD); `self-review`/`for-review` → `review_note` или PR; `done` → `acceptance_note` / merge evidence; новая задача → строка `Ценность:`
- подзадача = отдельный файл, один уровень, ссылка на родителя в поле `родитель`
- claim / доска / leases работают по детям; родитель — рамка и критерии done
- не копируй этот шаблон в бэклог без human confirmation при создании задачи

"""Hidden oracle for mixed-fork-join. Host-only: never copied into a workspace."""

import dataclasses
import importlib


def _mod(name):
    return importlib.import_module(f"stockplan.{name}")


def _item(sku, qty, reorder_at):
    return _mod("contract").Item(sku, qty, reorder_at)


def _raises(fn, *args):
    try:
        fn(*args)
    except ValueError:
        return
    raise AssertionError(f"expected ValueError for {args!r}")


def k_fields():
    item_cls = _mod("contract").Item
    assert [f.name for f in dataclasses.fields(item_cls)] == ["sku", "qty", "reorder_at"]
    item = item_cls("bolt", 3, 1)
    assert item == item_cls("bolt", 3, 1)
    assert hash(item) == hash(item_cls("bolt", 3, 1))
    try:
        item.qty = 9
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("Item must be frozen")


def k_validate():
    validate = _mod("contract").validate_item
    for bad in (_item("", 1, 1), _item(" bolt", 1, 1), _item("bolt ", 1, 1),
                _item("bolt", -1, 1), _item("bolt", 1, -1)):
        _raises(validate, bad)
    for good in (_item("bolt", 0, 0), _item("b", 7, 3)):
        assert validate(good) is good


def b_threshold():
    due = _mod("reorder").needs_reorder
    items = [_item("at", 4, 4), _item("below", 3, 4), _item("above", 5, 4), _item("zero", 0, 0)]
    assert due(items) == ["at", "below", "zero"]
    assert due([]) == []


def b_order():
    due = _mod("reorder").needs_reorder
    assert due([_item("washer", 0, 1), _item("Bolt", 0, 1), _item("nut", 0, 1)]) == [
        "Bolt", "nut", "washer"]
    _raises(due, [_item("nut", -1, 1)])


def c_sum():
    merge = _mod("merge").merge_counts
    got = merge([_item("nut", 2, 1), _item("bolt", 1, 1)], [_item("nut", 5, 1)])
    assert {i.sku: i.qty for i in got} == {"nut": 7, "bolt": 1}
    assert len(got) == 2


def c_reorder_max():
    merge = _mod("merge").merge_counts
    got = merge([_item("nut", 1, 4), _item("pin", 1, 9)], [_item("nut", 1, 6), _item("pin", 1, 2)])
    assert {i.sku: i.reorder_at for i in got} == {"nut": 6, "pin": 9}


def c_order_validate():
    merge = _mod("merge").merge_counts
    got = merge([_item("washer", 1, 1)], [_item("bolt", 1, 1), _item("nut", 1, 1)])
    assert [i.sku for i in got] == ["bolt", "nut", "washer"]
    assert merge([], []) == []
    _raises(merge, [_item("nut", 1, 1)], [_item("", 1, 1)])


def i_plan():
    plan = _mod("plan").restock_plan
    first = [_item("nut", 1, 4), _item("bolt", 10, 3)]
    second = [_item("nut", 2, 5), _item("pin", 0, 2)]
    assert plan(first, second) == {"nut": 7, "pin": 4}
    assert plan(first, second, 3) == {"nut": 12, "pin": 6}


def i_skip():
    plan = _mod("plan").restock_plan
    assert plan([_item("bolt", 4, 3)], [_item("bolt", 0, 3)]) == {}
    assert plan([_item("zero", 0, 0)], []) == {}
    assert plan([_item("edge", 3, 3)], [], 1) == {}


CRITERIA = {
    "K-fields": k_fields,
    "K-validate": k_validate,
    "B-threshold": b_threshold,
    "B-order": b_order,
    "C-sum": c_sum,
    "C-reorder-max": c_reorder_max,
    "C-order-validate": c_order_validate,
    "I-plan": i_plan,
    "I-skip": i_skip,
}

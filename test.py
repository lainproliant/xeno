import asyncio
import os
import random
import shutil
import sys
import tempfile
import time
import tracemalloc
import types
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

from xeno import (
    AsyncInjector,
    CircularDependencyError,
    ClassAttributes,
    InjectionError,
    InvalidResourceError,
    MethodAttributes,
    MissingDependencyError,
    MissingResourceError,
    SyncInjector,
    Tags,
    alias,
    build,
    const,
    inject,
    named,
    namespace,
    provide,
    singleton,
    using,
)
from xeno.build import DefaultEngineHook, Engine
from xeno.cookbook import sh
from xeno.pkg_config import PackageConfig
from xeno.recipe import BuildError, Recipe
from xeno.testing import OutputCapture

tracemalloc.start()


# --------------------------------------------------------------------
class CommonXenoTests(unittest.TestCase):
    @classmethod
    def make_injector(cls, *args):
        return AsyncInjector(*args)

    def test_ctor_injection(self):
        """Test to verify that constructor injection works properly."""

        class Module:
            @provide
            def name(self):
                return "Lain"

        class NamePrinter:
            def __init__(self, name):
                self.name = name

        injector = self.make_injector(Module())
        printer = injector.create(NamePrinter)
        self.assertEqual(printer.name, "Lain")

    def test_ctor_injection_with_methods(self):
        """Test to verify that constructor injection works properly,
        and that @inject methods are invoked on the resulting
        instance."""

        class Module:
            @provide
            def name(self):
                return "Lain"

            @provide
            def last_name(self):
                return "Musgrove"

        class NamePrinter:
            def __init__(self, name):
                self.name = name
                self.last_name = None

            @inject
            def set_last_name(self, last_name):
                self.last_name = last_name

        injector = self.make_injector(Module())
        printer = injector.create(NamePrinter)
        self.assertEqual(printer.name, "Lain")
        self.assertEqual(printer.last_name, "Musgrove")

    def test_instance_injection(self):
        """Test to verify that injection on an existing instance
        works without constructor injection."""

        class Module:
            @provide
            def name(self):
                return "Lain"

        class NamePrinter:
            def __init__(self):
                self.name = None

            @inject
            def set_name(self, name):
                self.name = name

        printer = NamePrinter()
        injector = self.make_injector(Module())
        injector.inject(printer)
        self.assertEqual(printer.name, "Lain")

    def test_missing_dependency_error(self):
        @namespace("MissingStuff")
        class Module:
            @provide
            def name(self, last_name):
                return "Lain %s" % last_name

        injector = self.make_injector(Module())
        with self.assertRaises(MissingDependencyError) as context:
            asyncio.run(injector.require("MissingStuff/name"))
        self.assertTrue(context.exception.name, "MissingStuff/name")
        self.assertTrue(context.exception.dep_name, "last_name")

    def test_namespace_internal_scope(self):
        @namespace("NamesAndStuff")
        class Module:
            @provide
            def name(self):
                return "Lain"

            @provide
            def last_name(self):
                return "Musgrove"

            @provide
            def full_name(self, name, last_name):
                return "%s %s" % (name, last_name)

        injector = self.make_injector(Module())
        full_name = injector.require("NamesAndStuff/full_name")
        self.assertEqual(full_name, "Lain Musgrove")

    def test_illegal_ctor_injection(self):
        """Test to verify that a constructor with invalid param types
        is not injectable."""

        class Module:
            @provide
            def name(self):
                return "Lain"

        class NamePrinter:
            def __init__(self, *names, name):
                self.names = names
                self.name = name

        injector = self.make_injector(Module())
        with self.assertRaises(InjectionError):
            injector.create(NamePrinter)

    def test_illegal_module_injection(self):
        """Test to verify that a module @provide method with invalid
        param types is not injectable."""

        class Module:
            @provide
            def name(self):
                return "Lain"

            @provide
            def last_name(self):
                return "Musgrove"

            @provide
            def full_name(self, *_, name, last_name):
                return name + last_name

        class NamePrinter:
            def __init__(self, full_name):
                self.full_name = full_name

            def print_name(self):
                print("My full name is %s" % self.full_name)

        with self.assertRaises(InjectionError):
            injector = self.make_injector(Module())
            printer = injector.create(NamePrinter)
            printer.print_name()

    def test_ctor_injection_with_defaults_not_provided(self):
        """Test to verify that a constructor with defaults that
        are not provided as resources is able to be called
        via the injector."""

        class Module:
            @provide
            def name(self):
                return "Lain"

        class NamePrinter:
            def __init__(self, name, last_name="Musgrove"):
                self.name = name
                self.last_name = last_name

        injector = self.make_injector(Module())
        printer = injector.create(NamePrinter)
        self.assertEqual(printer.name, "Lain")
        self.assertEqual(printer.last_name, "Musgrove")

    def test_ctor_injection_with_defaults_provided(self):
        """Test to verify that a constructor with defaults that
        are provided as resources are able to be called via
        the injector and that the injector provided resources
        are given instead of the defaults."""

        class Module:
            @provide
            def name(self):
                return "Lain"

            @provide
            def last_name(self):
                return "Musgrove"

        class NamePrinter:
            def __init__(self, name, last_name="Supe"):
                self.name = name
                self.last_name = last_name

        injector = self.make_injector(Module())
        printer = injector.create(NamePrinter)
        self.assertEqual(printer.name, "Lain")
        self.assertEqual(printer.last_name, "Musgrove")

    def test_cycle_check(self):
        class Module:
            @provide
            def a(self, b):
                return 1

            @provide
            def b(self, c):
                return 1

            @provide
            def c(self, a):
                return 1

        with self.assertRaises(CircularDependencyError):
            self.make_injector(Module())

    def test_create_no_ctor(self):
        class ClassNoCtor:
            def f(self):
                pass

        self.make_injector().create(ClassNoCtor)

    def test_inject_from_subclass(self):
        class Module:
            @provide
            def a(self):
                return 1

            @provide
            def b(self):
                return 2

        class Parent:
            @inject
            def inject(self, a):
                self.a = a

        class Child(Parent):
            @inject
            def inject(self, b):
                self.b = b

        injector = self.make_injector(Module())
        child = injector.create(Child)

        self.assertEqual(child.a, 1)
        self.assertEqual(child.b, 2)

    def test_provide_from_subclass(self):
        class SubModule:
            @provide
            def first_name(self):
                return "Lain"

        class Module(SubModule):
            @provide
            def last_name(self):
                return "Musgrove"

        class NamePrinter:
            def __init__(self, first_name, last_name):
                self.first_name = first_name
                self.last_name = last_name

        injector = self.make_injector(Module())
        printer = injector.create(NamePrinter)

        self.assertEqual(printer.first_name, "Lain")
        self.assertEqual(printer.last_name, "Musgrove")

    def test_injection_interceptor_for_provider(self):
        test = self

        class Module:
            @provide
            def phone_number(self):
                return 2060000000

            @provide
            def address_card(self, phone_number):
                test.assertTrue(isinstance(phone_number, str))
                return "Lain Musgrove: %s" % phone_number

        def intercept_phone_number(attrs, param_map, alias_map):
            if "phone_number" in param_map:
                param_map["phone_number"] = str(param_map["phone_number"])
            return param_map

        def intercept_address_card(attrs, param_map, alias_map):
            if "address_card" in param_map:
                param_map["address_card"] += "\n2000 1st Street, Seattle WA 98125"
            return param_map

        class AddressPrinter:
            def __init__(self, address_card):
                self.address_card = address_card

            def print_address(self):
                test.assertEqual(
                    self.address_card,
                    "Lain Musgrove: 2060000000\n2000 1st Street, Seattle WA 98125",
                )

        injector = self.make_injector(Module())
        injector.add_injection_interceptor(intercept_phone_number)
        injector.add_injection_interceptor(intercept_address_card)
        printer = injector.create(AddressPrinter)
        printer.print_address()

    def test_basic_alias(self):
        class ModuleA:
            @provide
            def really_long_name_for_a_resource_eh(self):
                return "Lain Musgrove"

            @provide
            @alias("name", "really_long_name_for_a_resource_eh")
            def person_name(self, name):
                return name

        @alias("birth_name", "person_name")
        class ModuleB:
            @provide
            def special_name(self, birth_name):
                return "Her Majesty Princess " + birth_name

        injector = self.make_injector(ModuleA(), ModuleB())
        name = injector.require("person_name")
        self.assertEqual(name, "Lain Musgrove")
        special_name = injector.require("special_name")
        self.assertTrue(special_name, "Her Majesty Princess Lain Musgrove")

    def test_bad_alias_loop(self):
        class ModuleA:
            @provide
            def name(self):
                return "Lain Musgrove"

            @provide
            @alias("full_name", "name")
            @alias("name", "full_name")
            def person_name(self, full_name):
                return full_name

        with self.assertRaises(InjectionError) as context:
            self.make_injector(ModuleA())
        self.assertTrue(str(context.exception).startswith("Alias loop detected"))

    def test_cross_namespace_alias(self):
        @namespace("a")
        class ModuleA:
            @provide
            def value(self):
                return 1

        @namespace("b")
        @alias("value", "a/value")
        class ModuleB:
            @provide
            def result(self, value):
                return value + 1

        injector = self.make_injector(ModuleA(), ModuleB())
        self.assertEqual(2, injector.require("b/result"))

    def test_root_to_namespace_alias(self):
        @namespace("a")
        class ModuleA:
            @provide
            def value(self):
                return 1

        class ModuleB:
            @provide
            @alias("value", "a/value")
            def result(self, value):
                return value + 1

        injector = self.make_injector(ModuleA(), ModuleB())
        self.assertEqual(2, injector.require("result"))

    def test_nested_namespaces(self):
        @namespace("com/lainproliant/stuff")
        class ModuleA:
            @provide
            def name(self):
                return "Lain Musgrove"

        @namespace("com/lainproliant/other_stuff")
        class ModuleB:
            @provide
            @alias("name", "com/lainproliant/stuff/name")
            def address(self, name):
                return "%s: Seattle, WA" % name

        @using("com/lainproliant/other_stuff")
        class ModuleC:
            @provide
            @named("address-with-zip")
            def address(self, address):
                return address + " 98119"

        injector = self.make_injector(ModuleA(), ModuleB(), ModuleC())
        address = injector.require("address-with-zip")
        self.assertEqual(address, "Lain Musgrove: Seattle, WA 98119")

    def test_overwrite_namespaced_variable(self):
        @namespace("com/lainproliant")
        class ModuleA:
            @provide
            def name(self):
                return "Lain Musgrove"

        class ModuleB:
            @provide
            @named("com/lainproliant/name")
            def name(self):
                return "Jenna Musgrove"

        injector = self.make_injector(ModuleA(), ModuleB())
        name = injector.require("com/lainproliant/name")
        self.assertEqual(name, "Jenna Musgrove")

    def test_dependency_tree(self):
        @const("last_name", "Rex")
        @const("first_name", "Pontifex")
        @const("street", "1024 Street Ave")
        @const("city", "Seattle, WA")
        @const("zip_code", 98101)
        class ModuleA:
            @provide
            def name(self, first_name, last_name):
                return "%s %s" % (first_name, last_name)

            @provide
            def address(self, name, street, city, zip_code):
                return "%s\n%s\n%s %d" % (name, street, city, zip_code)

        injector = self.make_injector(ModuleA())
        address = injector.require("address")
        dep_tree = injector.get_dependency_tree("address")
        self.assertTrue("name" in dep_tree)
        self.assertTrue("street" in dep_tree)
        self.assertTrue("city" in dep_tree)
        self.assertTrue("zip_code" in dep_tree)
        self.assertTrue("first_name" in dep_tree["name"])
        self.assertTrue("last_name" in dep_tree["name"])
        self.assertEqual("Pontifex Rex\n1024 Street Ave\nSeattle, WA 98101", address)

    def test_injector_provide(self):
        class ModuleA:
            @provide
            def a(self, b):
                return b + 2

            @provide
            def b(self):
                return 1

            @singleton
            def c(self, a, b):
                return a + b + 1

        injector = self.make_injector(ModuleA())
        self.assertEqual(injector.require("a"), 3)
        self.assertEqual(injector.require("b"), 1)
        self.assertEqual(injector.require("c"), 5)
        injector.provide("b", 3)
        self.assertEqual(injector.require("a"), 5)
        self.assertEqual(injector.require("b"), 3)
        self.assertEqual(injector.require("c"), 5)  # singleton should not change
        injector.provide("a", 1)
        self.assertEqual(injector.require("a"), 1)
        self.assertEqual(injector.require("b"), 3)
        self.assertEqual(injector.require("c"), 5)  # singleton should not change
        injector.provide("c", 6)
        self.assertEqual(injector.require("a"), 1)
        self.assertEqual(injector.require("b"), 3)
        self.assertEqual(injector.require("c"), 6)  # singleton was replaced

    def test_dependency_graph(self):
        class ModuleA:
            @provide
            def a(self, b):
                return b + 1

            @provide
            def b(self):
                return 1

            @provide
            def c(self, a, b):
                return a + b + 1

        injector = self.make_injector(ModuleA())
        dep_graph_a = injector.get_dependency_graph("a")
        dep_graph_b = injector.get_dependency_graph("b")
        dep_graph_c = injector.get_dependency_graph("c")

        self.assertListEqual([*sorted(dep_graph_a["a"])], ["b"])
        self.assertListEqual([*sorted(dep_graph_a["b"])], [])
        self.assertEqual(len(dep_graph_a), 2)

        self.assertListEqual([*sorted(dep_graph_b["b"])], [])
        self.assertEqual(len(dep_graph_b), 1)

        self.assertListEqual([*sorted(dep_graph_c["a"])], ["b"])
        self.assertListEqual([*sorted(dep_graph_c["b"])], [])
        self.assertListEqual([*sorted(dep_graph_c["c"])], ["a", "b"])
        self.assertEqual(len(dep_graph_c), 3)

    def test_get_resource_attrs(self):
        class ModuleA:
            @singleton
            def a(self):
                return 1

            @provide
            def b(self):
                return 0

        injector = self.make_injector(ModuleA())
        self.assertTrue(injector.get_resource_attributes("a").check(Tags.SINGLETON))
        self.assertFalse(injector.get_resource_attributes("b").check(Tags.SINGLETON))

    def test_unbind_singletons(self):
        class ModuleA:
            @singleton
            def a(self, b):
                return b + 1

            @provide
            def b(self):
                return 1

            @singleton
            def c(self, a):
                return str(a)

        injector = self.make_injector(ModuleA())
        self.assertEqual(injector.require("a"), 2)
        self.assertEqual(injector.require("b"), 1)
        self.assertEqual(injector.require("c"), "2")

        injector.provide("b", 10)
        self.assertEqual(injector.require("a"), 2)
        self.assertEqual(injector.require("b"), 10)
        self.assertEqual(injector.require("c"), "2")

        with self.assertRaises(MissingResourceError):
            injector.unbind_singleton("d")

        with self.assertRaises(InvalidResourceError):
            injector.unbind_singleton("b")

        injector.unbind_singleton("a")
        self.assertEqual(injector.require("a"), 11)
        self.assertEqual(injector.require("b"), 10)
        self.assertEqual(injector.require("c"), "2")

        injector.unbind_singleton("c")
        self.assertEqual(injector.require("a"), 11)
        self.assertEqual(injector.require("b"), 10)
        self.assertEqual(injector.require("c"), "11")

        injector.provide("b", 100)
        injector.unbind_singleton(unbind_all=True)
        self.assertEqual(injector.require("a"), 101)
        self.assertEqual(injector.require("b"), 100)
        self.assertEqual(injector.require("c"), "101")

    def test_namespace_scope_breakout(self):
        @namespace("A")
        class ModuleA:
            @provide
            def first_name(self):
                return "Lain"

            @provide
            def last_name(self):
                return "Musgrove"

        @namespace("B")
        class ModuleB:
            @provide
            @named("/A/last_name")
            def last_name_override(self):
                return "Musgrove"

            @provide
            def address(self):
                return "123 Main St."

            @provide
            @alias("name", "A/first_name")
            def first_name(self, name):
                return name[::-1]

        injector = self.make_injector(ModuleA(), ModuleB())
        first_name = injector.require("A/first_name")
        last_name = injector.require("A/last_name")
        address = injector.require("B/address")
        weird_name = injector.require("B/first_name")
        self.assertEqual(first_name, "Lain")
        self.assertEqual(last_name, "Musgrove")
        self.assertEqual(address, "123 Main St.")
        self.assertEqual(weird_name, "niaL")

    def test_dependencies(self):
        class ModuleA:
            @provide
            def a(self):
                return 1

            @provide
            def b(self):
                return 2

            @provide
            def c(self):
                return 3

            @provide
            def d(self, a, b, c):
                return 4

            @provide
            def e(self, b, d):
                return 5

        injector = self.make_injector(ModuleA())
        self.assertListEqual([*sorted(injector.get_dependencies("d"))], ["a", "b", "c"])
        self.assertListEqual([*sorted(injector.get_dependencies("e"))], ["b", "d"])
        self.assertListEqual([*sorted(injector.get_dependencies("a"))], [])

    def test_namespace_get_leaves(self):
        @namespace("com/example/core")
        class Core:
            @provide
            def first_thing(self):
                return 1

            @provide
            def second_thing(self):
                return 2

        @namespace("com/example/impl")
        class Impl:
            @provide
            def third_thing(self, injector):
                return 3

            @provide
            def fourth_thing(self):
                return 4

        injector = self.make_injector(Core(), Impl())
        ns = injector.get_namespace()
        assert ns is not None
        recursive_list = ns.get_leaves(recursive=True)
        core_ns = ns.get_namespace("com/example/core")
        impl_ns = ns.get_namespace("com/example/impl")
        assert core_ns is not None
        assert impl_ns is not None
        core_list = core_ns.get_leaves()
        impl_list = impl_ns.get_leaves()

        self.assertEqual(len(recursive_list), 4)
        self.assertEqual(len(core_list), 2)
        self.assertEqual(len(impl_list), 2)
        self.assertTrue("first_thing" in core_list)
        self.assertTrue("second_thing" in core_list)
        self.assertTrue("third_thing" in impl_list)
        self.assertTrue("fourth_thing" in impl_list)

    def test_resource_name_attribute(self):
        outerSelf = self

        @namespace("com/example/core")
        class Core:
            @provide
            def apples(self):
                attrs = MethodAttributes.for_method(self.apples)
                assert attrs is not None
                outerSelf.assertEqual(
                    attrs.get(Tags.RESOURCE_FULL_NAME), "com/example/core/apples"
                )
                return "apples"

            @provide
            def oranges(self):
                attrs = MethodAttributes.for_method(self.oranges)
                assert attrs is not None
                outerSelf.assertEqual(
                    attrs.get(Tags.RESOURCE_FULL_NAME), "com/example/core/oranges"
                )
                return Path("oranges")

        injector = self.make_injector(Core())

        def assert_resource_name(key, attrs):
            self.assertEqual(key, attrs.get(Tags.RESOURCE_FULL_NAME))
            return True

        injector.scan_resources(assert_resource_name)
        attrs = injector.get_resource_attributes("com/example/core/apples")
        self.assertEqual(attrs.get(Tags.RESOURCE_FULL_NAME), "com/example/core/apples")

    def test_inject_decorated_provider(self):
        def fancy(f):
            @MethodAttributes.wraps(f)
            def wrapper(*args, **kwargs):
                result = f(*args, **kwargs)
                return "The Right Honourable %s" % result

            return wrapper

        class Core:
            @provide
            @fancy
            def name(self, first_name, last_name):
                return "%s %s" % (first_name, last_name)

            @provide
            def first_name(self):
                return "Lain"

            @provide
            def last_name(self):
                return "Musgrove"

        injector = self.make_injector(Core())
        self.assertEqual("The Right Honourable Lain Musgrove", injector.require("name"))

    def test_ordered_dependencies(self):
        class Test:
            @provide
            def a(self):
                pass

            @provide
            def b(self, a):
                pass

            @provide
            def c(self, a):
                pass

            @provide
            def d(self, b, c):
                pass

            @provide
            def e(self, d, c, b, a):
                pass

        injector = self.make_injector(Test())
        self.assertListEqual(
            injector.get_ordered_dependencies("e"), ["a", "b", "c", "d"]
        )

    def test_outsider_provide(self):
        injector = self.make_injector()
        prov = injector.provide

        @prov
        def cheese(milk):
            return "cheese"

        @prov
        def milk():
            return "milk"

        @prov
        def eggs():
            return "eggs"

        @prov
        def omelette_du_fromage(cheese, eggs):
            return "omelette_du_fromage = %s + %s" % (cheese, eggs)

        omelette = injector.require("omelette_du_fromage")
        self.assertEqual(omelette, "omelette_du_fromage = cheese + eggs")

    def test_class_attribute_docstring(self):
        class A:
            """This is a docstring."""

            pass

        instance = A()

        attrs = ClassAttributes.for_class(A)
        self.assertEqual(attrs.get(Tags.DOCS), "This is a docstring.")
        attrs = ClassAttributes.for_object(instance)
        self.assertEqual(attrs.get(Tags.DOCS), "This is a docstring.")

    def test_method_attribute_docstring(self):
        class A:
            def f(self):
                """This is a docstring."""
                pass

        instance = A()

        def bare_function():
            """This is another doc string."""
            pass

        attrs = MethodAttributes.for_method(A.f)
        self.assertEqual(attrs.get(Tags.DOCS), "This is a docstring.")
        attrs = MethodAttributes.for_method(instance.f)
        self.assertEqual(attrs.get(Tags.DOCS), "This is a docstring.")
        attrs = MethodAttributes.for_method(bare_function)
        self.assertEqual(attrs.get(Tags.DOCS), "This is another doc string.")

    def test_attribute_wrap_target_with_no_params(self):
        injector = self.make_injector()

        def stringify(f):
            @MethodAttributes.wraps(f)
            def wrapper(*args, **kwargs):
                result = f(*args, **kwargs)
                return str(result)

            return wrapper

        @injector.provide
        @stringify
        def bignum():
            return 1234567890

        value = injector.require("bignum")
        self.assertIsInstance(value, str)
        self.assertEqual(value, "1234567890")

    def test_yielding_provider(self):
        injector = self.make_injector()

        @injector.provide
        def sequence_A():
            for i in range(10):
                yield i

        @injector.provide
        def sequence_B(sequence_A):
            yield from reversed(list(sequence_A))

        value = injector.require("sequence_A")
        self.assertTrue(isinstance(value, types.GeneratorType))
        value = [*value]
        self.assertEqual(value, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])

        # We should be given a new generator this time.
        value = injector.require("sequence_A")
        self.assertTrue(isinstance(value, types.GeneratorType))
        value = [*value]
        self.assertEqual(value, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])

        # The `sequence_B` provider should get its own `sequence_A`
        # generator, too.
        value = injector.require("sequence_B")
        self.assertTrue(isinstance(value, types.GeneratorType))
        value = [*value]
        self.assertEqual(value, [9, 8, 7, 6, 5, 4, 3, 2, 1, 0])


# --------------------------------------------------------------------
class SyncXenoTests(CommonXenoTests):
    @classmethod
    def make_injector(cls, *args):
        return SyncInjector(*args)


# --------------------------------------------------------------------
class AsyncXenoTests(unittest.TestCase):
    def test_async_resource_concurrency(self):
        class Test:
            @provide
            def target(self, a, b, c):
                pass

            @provide
            async def a(self):
                await asyncio.sleep(1)

            @provide
            async def b(self):
                await asyncio.sleep(1)

            @provide
            async def c(self):
                await asyncio.sleep(1)

        injector = AsyncInjector(Test())
        start_time = datetime.now()
        injector.require("target")
        end_time = datetime.now()
        self.assertTrue(end_time - start_time < timedelta(seconds=2))


# --------------------------------------------------------------------
class XenoEnvironmentTests(unittest.TestCase):
    def test_pkgconfig(self):
        pyenv = PackageConfig("python3 >= 3.10")
        self.assertTrue("python" in pyenv.cflags)
        expected_cflags = pyenv.cflags + " -g -I./include"
        newenv = pyenv + dict(CFLAGS=["-g", "-I./include"])
        self.assertEqual(newenv["CFLAGS"], expected_cflags)

    def test_environment_update(self):
        from xeno.shell import Environment

        env = Environment(CC="clang", CFLAGS="-I./include", LDFLAGS="-g")
        print(f'before {env=}')
        env.update(
            append="CFLAGS,LDFLAGS",
            CC="gcc",
            CFLAGS="-I./deps/include",
            LDFLAGS="-lpthread",
        )
        print(f'after {env=}')
        self.assertEqual(
            Environment(
                CC="gcc", CFLAGS="-I./include -I./deps/include", LDFLAGS="-g -lpthread"
            ),
            env
        )


# --------------------------------------------------------------------
class XenoBuildTests(unittest.TestCase):
    def on_event(self, event):
        print(
            f"{event.name} ({event.context.memoize}): {event.context.result_or(None)} @ {event.context.path()}: {event.data}"
        )

    def bus_hook(self, bus):
        print()
        bus.listen(self.on_event)

    def test_basic_build(self):
        engine = build.Engine()

        @engine.recipe
        def add(a, b):
            return a + b

        @engine.recipe
        def add_and_two(a, b):
            return add(add(a, b), 2)

        @engine.task
        def make_three():
            return add(1, 2)

        @engine.task
        def make_five(make_three):
            return add(2, make_three)

        @engine.task(default=True)
        def make_seven(make_five):
            return add_and_two(make_five, 0)

        result = engine.build()
        self.assertEqual(result, [7])

        result = engine.build("make_three", "make_five", "make_seven")
        self.assertEqual(result, [3, 5, 7])

    def test_yielding_provider_build(self):
        engine = build.Engine()

        @engine.provide
        def generated_sequence():
            for i in range(10):
                yield i

        @engine.recipe
        def sequence_printer(seq):
            # xeno.build should be expanding generators returned
            # from providers into static sequences.
            self.assertTrue(isinstance(seq, list))
            self.assertEqual(seq, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
            print(seq)
            return 0

        @engine.task(default=True)
        def print_sequence(generated_sequence):
            return sequence_printer(generated_sequence)

        result = engine.build()
        self.assertEqual(result, [0])

    def test_shell_recipe_and_async_timing(self):
        from xeno.build import engine, provide, recipe, task
        from xeno.cookbook import sh

        sh.env = dict(CAT="cat")

        class Format(Recipe.Format):
            def sigil(self, r):
                return f'{r.name}({r.arg("n")}, {r.arg("sec")})'

        @recipe(fmt=Format())
        async def slowly_make_number(n, sec=1):
            await asyncio.sleep(sec)
            return n

        @provide
        def file():
            return Path("LICENSE")

        @task
        def print_file(file):
            return sh("{CAT} {file}", file=file)

        @task
        def slow_number():
            return slowly_make_number(99)

        @task
        def print_file_2(file):
            return sh(["{CAT}", file], interact=True)

        @task
        def two_slow_numbers():
            return [slowly_make_number(5, 2), slowly_make_number(10, 2)]

        @task
        def lots_of_slow_numbers():
            return [slowly_make_number(x, random.randint(1, 4)) for x in range(0, 10)]

        result = engine.build("print_file", "slow_number")
        self.assertEqual(result, [0, 99])

        result = engine.build("print_file_2", "slow_number")
        self.assertEqual(result, [0, 99])

        start_time = datetime.now()
        result = engine.build("two_slow_numbers")
        self.assertEqual(result, [[5, 10]])
        end_time = datetime.now()
        self.assertTrue(end_time - start_time < timedelta(seconds=3))

        result = engine.build("lots_of_slow_numbers")

    def test_file_target_recipes(self):
        engine = Engine()

        uid = str(uuid.uuid4())

        try:

            @engine.provide
            def unique_name():
                return str(uid)

            @engine.recipe
            def hello_file(target):
                return sh(
                    "echo 'Making a file...' && echo 'Hello, world!' > {target}",
                    target=target,
                )

            @engine.task(keep=True)
            def output_dir(unique_name):
                return sh(
                    "echo 'Making directory...' && mkdir {target}",
                    target=Path("/tmp") / unique_name,
                )

            @engine.task(default=True, dep="output_dir")
            def make_hello_file(output_dir):
                return hello_file(output_dir.target / "hello.txt")

            @engine.provide
            def filenames():
                return ["apples", "bananas", "oranges"]

            @engine.task(dep="output_dir")
            def more_hello_files(filenames, output_dir):
                return [hello_file(output_dir.target / name) for name in filenames]

            result = engine.build()
            self.assertEqual(str(result[0]), f"/tmp/{uid}/hello.txt")
            self.assertTrue(result[0].exists())

            engine.build("-c")
            self.assertFalse(result[0].exists())

            result = engine.build()
            self.assertEqual(str(result[0]), f"/tmp/{uid}/hello.txt")
            self.assertTrue(result[0].exists())

            result = engine.build("-R")
            self.assertEqual(str(result[0]), f"/tmp/{uid}/hello.txt")
            self.assertTrue(result[0].exists())

            engine.build("-x")
            self.assertFalse(result[0].exists())

            print(engine.build("-l"))
            print(engine.build("-L"))
            print(engine.build("more_hello_files"))

            print(engine.build("more_hello_files", "-c"))

        finally:
            if os.path.exists(f"/tmp/{uid}"):
                shutil.rmtree(f"/tmp/{uid}")

    def test_file_components_updated(self):
        engine = Engine()
        engine.add_hook(DefaultEngineHook())

        uid = str(uuid.uuid4())
        output_dir = Path("/tmp") / str(uid)

        try:
            output_dir.mkdir()

            input_file = output_dir / "input.txt"
            with open(input_file, "w") as outfile:
                outfile.write("apples")

            self.assertTrue(input_file.exists())
            with open(input_file, "r") as infile:
                self.assertEqual("apples", infile.read())

            @engine.task
            def copy_file():
                return sh(
                    "cat {input} >> {target}",
                    input=input_file,
                    target=output_dir / "out.txt",
                )

            copy_file_recipe = cast(Recipe, engine.injector.require("copy_file"))
            self.assertFalse(copy_file_recipe.done())

            engine.build("copy_file")
            self.assertTrue(copy_file_recipe.done())

            time.sleep(0.25)

            now = datetime.now()
            input_file = output_dir / "input.txt"
            with open(input_file, "w") as outfile:
                outfile.write("oranges")

            time.sleep(0.25)

            self.assertFalse(copy_file_recipe.done())
            self.assertTrue(copy_file_recipe.outdated(now))

            engine.build("copy_file")
            now = datetime.now()
            self.assertTrue(copy_file_recipe.done())
            self.assertFalse(copy_file_recipe.outdated(now))

        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_target_queries(self):
        engine = Engine()

        @engine.recipe
        def passthru(x):
            return x

        @engine.task
        def apples():
            return passthru(1)

        @engine.task
        def oranges():
            return passthru(2)

        self.assertEqual(0, engine.build("-Q", "apples"))
        self.assertEqual(0, engine.build("-Q", "apples,oranges"))
        self.assertEqual(1, engine.build("-Q", "apples,bananas"))
        self.assertEqual(1, engine.build("-Q", "oranges,bananas"))
        self.assertEqual(2, engine.build("-Q", "pineapples,bananas"))

    def test_failed_build(self):
        engine = Engine()
        engine.add_hook(DefaultEngineHook())

        @engine.recipe
        def forced_failure():
            return sh("exit 1")

        @engine.task(default=True)
        def default_target():
            return forced_failure()

        with self.assertRaises(BuildError):
            engine.build(raise_errors=True)


# --------------------------------------------------------------------
class XenoTestingUtilsTests(unittest.TestCase):
    def test_output_capture(self):
        original_stdout = sys.stdout

        with OutputCapture(stdout=True) as capture:
            self.assertIs(sys.stdout, capture.stdout)
            print("Hello!")
            self.assertEqual(capture.stdout.getvalue(), "Hello!\n")

        self.assertIs(sys.stdout, original_stdout)


# --------------------------------------------------------------------
class XenoBatteriesIncludedTests(unittest.TestCase):
    def setUp(self):
        self.prefix = Path(tempfile.mkdtemp())
        shutil.copytree("./testsrc", self.prefix / "testsrc")
        self.prev_cwd = os.getcwd()
        os.chdir(self.prefix)

    def tearDown(self):
        shutil.rmtree(self.prefix)
        os.chdir(self.prev_cwd)

    def test_void(self):
        from xeno.recipes.c import compile

        engine = Engine()
        engine.add_hook(DefaultEngineHook())

        @engine.task(default=True)
        def hello():
            return sh(
                compile("testsrc/void/void.c", target="the-void"),
                result=sh.result.STDOUT,
            )

        result = engine.build("-D")
        self.assertEqual([], result[0])

    def test_hello_c(self):
        from xeno.recipes.c import compile

        engine = Engine()
        engine.add_hook(DefaultEngineHook())

        @engine.task(default=True)
        def hello():
            return sh(compile("testsrc/hello/c/hello.c"), result=sh.result.STDOUT)

        result = engine.build()
        self.assertEqual(["Hello, world!"], result[0])


# --------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()

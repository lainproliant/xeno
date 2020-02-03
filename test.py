import unittest

from xeno import (
    CircularDependencyError, MethodAttributes, MissingResourceError,
    provide, inject, namespace, alias, named, using, const,
    singleton, Injector, MissingDependencyError, InjectionError,
    InvalidResourceError
)


class XenoTests(unittest.TestCase):
    def test_ctor_injection(self):
        """Test to verify that constructor injection works properly."""

        class Module:
            @provide
            def name(self):
                return "Lain"

        class NamePrinter:
            def __init__(self, name):
                self.name = name

        injector = Injector(Module())
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

        injector = Injector(Module())
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
        injector = Injector(Module())
        injector.inject(printer)
        self.assertEqual(printer.name, "Lain")

    def test_missing_dependency_error(self):
        @namespace("MissingStuff")
        class Module:
            @provide
            def name(self, last_name):
                return "Lain %s" % last_name

        injector = Injector(Module())
        with self.assertRaises(MissingDependencyError) as context:
            injector.require("MissingStuff/name")
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

        injector = Injector(Module())
        full_name = injector.require("NamesAndStuff/full_name")
        self.assertTrue(full_name, "Lain Musgrove")

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

        injector = Injector(Module())
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
            def full_name(self, *arg, name, last_name):
                return name + last_name

        class NamePrinter:
            def __init__(self, full_name):
                self.full_name = full_name

            def print_name(self):
                print("My full name is %s" % self.full_name)

        with self.assertRaises(InjectionError):
            injector = Injector(Module())
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

        injector = Injector(Module())
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
            def __init__(self, name, last_name="Musgrove"):
                self.name = name
                self.last_name = last_name

        injector = Injector(Module())
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
            Injector(Module())

    def test_create_no_ctor(self):
        class ClassNoCtor:
            def f(self):
                pass

        Injector().create(ClassNoCtor)

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

        injector = Injector(Module())
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

        injector = Injector(Module())
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
                param_map["address_card"] += \
                    "\n2000 1st Street, Seattle WA 98125"
            return param_map

        class AddressPrinter:
            def __init__(self, address_card):
                self.address_card = address_card

            def print_address(self):
                test.assertEqual(
                    self.address_card,
                    "Lain Musgrove: 2060000000\n2000 1st Street, Seattle WA 98125",
                )

        injector = Injector(Module())
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

        injector = Injector(ModuleA(), ModuleB())
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
            Injector(ModuleA())
        self.assertTrue(str(context.exception).startswith(
            "Alias loop detected"))

    def test_cross_namespace_alias(self):
        @namespace("a")
        class ModuleA:
            @provide
            def value(self):
                return 1

        @namespace("b")
        @alias('value', 'a/value')
        class ModuleB:
            @provide
            def result(self, value):
                return value + 1

        injector = Injector(ModuleA(), ModuleB())
        self.assertEqual(2, injector.require("b/result"))

    def test_root_to_namespace_alias(self):
        @namespace("a")
        class ModuleA:
            @provide
            def value(self):
                return 1

        class ModuleB:
            @provide
            @alias('value', 'a/value')
            def result(self, value):
                return value + 1

        injector = Injector(ModuleA(), ModuleB())
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
            @alias('name', 'com/lainproliant/stuff/name')
            def address(self, name):
                return "%s: Seattle, WA" % name

        @using("com/lainproliant/other_stuff")
        class ModuleC:
            @provide
            @named("address-with-zip")
            def address(self, address):
                return address + " 98119"

        injector = Injector(ModuleA(), ModuleB(), ModuleC())
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

        injector = Injector(ModuleA(), ModuleB())
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

        injector = Injector(ModuleA())
        address = injector.require("address")
        dep_tree = injector.get_dependency_tree("address")
        self.assertTrue("name" in dep_tree)
        self.assertTrue("street" in dep_tree)
        self.assertTrue("city" in dep_tree)
        self.assertTrue("zip_code" in dep_tree)
        self.assertTrue("first_name" in dep_tree["name"])
        self.assertTrue("last_name" in dep_tree["name"])
        self.assertEqual("Pontifex Rex\n1024 Street Ave\nSeattle, WA 98101",
                         address)

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

        injector = Injector(ModuleA())
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

        injector = Injector(ModuleA())
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

        injector = Injector(ModuleA())
        self.assertTrue(injector.get_resource_attributes("a").check("singleton"))
        self.assertFalse(injector.get_resource_attributes("b").check("singleton"))

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

        injector = Injector(ModuleA())
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
            @alias('name', 'A/first_name')
            def first_name(self, name):
                return name[::-1]

        injector = Injector(ModuleA(), ModuleB())
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

        injector = Injector(ModuleA())
        self.assertListEqual([*sorted(injector.get_dependencies("d"))],
                             ["a", "b", "c"])
        self.assertListEqual([*sorted(injector.get_dependencies("e"))],
                             ["b", "d"])
        self.assertListEqual([*sorted(injector.get_dependencies("a"))],
                             [])

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

        injector = Injector(Core(), Impl())
        ns = injector.get_namespace()
        recursive_list = ns.get_leaves(recursive=True)
        core_ns = ns.get_namespace("com/example/core")
        impl_ns = ns.get_namespace("com/example/impl")
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
                outerSelf.assertEqual(
                    attrs.get("resource-name"), "com/example/core/apples"
                )
                return "apples"

            @provide
            def oranges(self):
                attrs = MethodAttributes.for_method(self.oranges)
                outerSelf.assertEqual(
                    attrs.get("resource-name"), "com/example/core/oranges"
                )
                return "oranges"

        injector = Injector(Core())

        def assert_resource_name(key, attrs):
            self.assertEqual(key, attrs.get("resource-name"))
            return True

        injector.scan_resources(assert_resource_name)
        attrs = injector.get_resource_attributes("com/example/core/apples")
        self.assertEqual(attrs.get("resource-name"), "com/example/core/apples")

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

        injector = Injector(Core())
        self.assertEqual("The Right Honourable Lain Musgrove",
                         injector.require("name"))

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

        injector = Injector(Test())
        self.assertListEqual(injector.get_ordered_dependencies('e'),
                             ['a', 'b', 'c', 'd'])


if __name__ == "__main__":
    unittest.main()

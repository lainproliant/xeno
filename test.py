import unittest
from xeno import *

#--------------------------------------------------------------------
class XenoTests(unittest.TestCase):
    def test_ctor_injection(self):
        """Test to verify that constructor injection works properly."""
        class Module:
            @provide
            def name(self):
                return 'Lain'

        class NamePrinter:
            def __init__(self, name):
                self.name = name

        injector = Injector(Module())
        printer = injector.create(NamePrinter)
        self.assertEqual(printer.name, 'Lain')

    def test_ctor_injection_with_methods(self):
        """Test to verify that constructor injection works properly,
           and that @inject methods are invoked on the resulting
           instance."""

        class Module:
            @provide
            def name(self):
                return 'Lain'

            @provide
            def last_name(self):
                return 'Supe'

        class NamePrinter:
            def __init__(self, name):
                self.name = name
                self.last_name = None

            @inject
            def set_last_name(self, last_name):
                self.last_name = last_name

        injector = Injector(Module())
        printer = injector.create(NamePrinter)
        self.assertEqual(printer.name, 'Lain')
        self.assertEqual(printer.last_name, 'Supe')

    def test_instance_injection(self):
        """Test to verify that injection on an existing instance
           works without constructor injection."""
        class Module:
            @provide
            def name(self):
                return 'Lain'

        class NamePrinter:
            def __init__(self):
                self.name = None

            @inject
            def set_name(self, name):
                self.name = name

        printer = NamePrinter()
        injector = Injector(Module())
        injector.inject(printer)
        self.assertEqual(printer.name, 'Lain')

    def test_missing_dependency_error(self):
        @namespace("MissingStuff")
        class Module:
            @provide
            def name(self, last_name):
                return 'Lain %s' % last_name

        injector = Injector(Module())
        with self.assertRaises(MissingDependencyError) as context:
            injector.require('MissingStuff::name')
        self.assertTrue(context.exception.name, 'MissingStuff::name')
        self.assertTrue(context.exception.dep_name, 'last_name')

    def test_namespace_internal_scope(self):
        @namespace('NamesAndStuff')
        class Module:
            @provide
            def name(self):
                return 'Lain'

            @provide
            def last_name(self):
                return 'Supe'

            @provide
            def full_name(self, name, last_name):
                return '%s %s' % (name, last_name)

        injector = Injector(Module())
        full_name = injector.require('NamesAndStuff::full_name')
        self.assertTrue(full_name, 'Lain Supe')

    def test_illegal_ctor_injection(self):
        """Test to verify that a constructor with invalid param types
           is not injectable."""

        class Module:
            @provide
            def name(self):
                return 'Lain'

        class NamePrinter:
            def __init__(self, *names, name):
                self.names = names
                self.name = name

        injector = Injector(Module())
        with self.assertRaises(InjectionError):
            printer = injector.create(NamePrinter)

    def test_illegal_module_injection(self):
        """Test to verify that a module @provide method with invalid
           param types is not injectable."""

        class Module:
            @provide
            def name(self):
                return 'Lain'

            @provide
            def last_name(self):
                return 'Supe'

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
                return 'Lain'

        class NamePrinter:
            def __init__(self, name, last_name = 'Supe'):
                self.name = name
                self.last_name = last_name

        injector = Injector(Module())
        printer = injector.create(NamePrinter)
        self.assertEqual(printer.name, 'Lain')
        self.assertEqual(printer.last_name, 'Supe')

    def test_ctor_injection_with_defaults_provided(self):
        """Test to verify that a constructor with defaults that
           are provided as resources are able to be called via
           the injector and that the injector provided resources
           are given instead of the defaults."""

        class Module:
            @provide
            def name(self):
                return 'Lain'

            @provide
            def last_name(self):
                return 'Musgrove'

        class NamePrinter:
            def __init__(self, name, last_name = 'Supe'):
                self.name = name
                self.last_name = last_name

        injector = Injector(Module())
        printer = injector.create(NamePrinter)
        self.assertEqual(printer.name, 'Lain')
        self.assertEqual(printer.last_name, 'Musgrove')

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
            injector = Injector(Module())

    def test_create_no_ctor(self):
        class ClassNoCtor:
            def f(self):
                pass

        injector = Injector()
        c = injector.create(ClassNoCtor)

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
                return "Supe"

        class NamePrinter:
            def __init__(self, first_name, last_name):
                self.first_name = first_name
                self.last_name = last_name

        injector = Injector(Module())
        printer = injector.create(NamePrinter)

        self.assertEqual(printer.first_name, 'Lain')
        self.assertEqual(printer.last_name, 'Supe')

    def test_injection_interceptor_for_provider(self):
        test = self
        class Module:
            @provide
            def phone_number(self):
                return 2060000000

            @provide
            def address_card(self, phone_number):
                test.assertTrue(isinstance(phone_number, str))
                return "Lain Supe: %s" % phone_number

        def intercept_phone_number(attrs, dependency_map):
            if 'phone_number' in dependency_map:
                dependency_map['phone_number'] = str(dependency_map['phone_number'])
            return dependency_map

        def intercept_address_card(attrs, dependency_map):
            if 'address_card' in dependency_map:
                dependency_map['address_card'] += '\n2000 Street Blvd, Seattle WA 98125'
            return dependency_map

        class AddressPrinter:
            def __init__(self, address_card):
                self.address_card = address_card

            def print_address(self):
                test.assertEqual(self.address_card, "Lain Supe: 2060000000\n2000 Street Blvd, Seattle WA 98125")

        injector = Injector(Module())
        injector.add_injection_interceptor(intercept_phone_number)
        injector.add_injection_interceptor(intercept_address_card)
        printer = injector.create(AddressPrinter)
        printer.print_address()

    def test_namespaces_and_annotated_resource_params(self):
        @namespace('A')
        class ModuleA:
            @provide
            @named('first-name')
            def first(self):
                return 'Lain'

        @namespace('B')
        class ModuleB:
            @provide
            @named('last-name')
            def last(self):
                return 'Supe'

        @namespace('C')
        @using('A')
        class ModuleC:
            @provide
            def name(self, first: 'first-name', last: 'B::last-name'):
                return '%s %s' % (first, last)

        class NameContainer:
            @inject
            def __init__(self, name: 'C::name'):
                self.name = name

            def get(self):
                return self.name

        injector = Injector(ModuleA(), ModuleB(), ModuleC())
        name = injector.create(NameContainer).get()
        self.assertEqual(name, 'Lain Supe')

    def test_basic_alias(self):
        class ModuleA:
            @provide
            def really_long_name_for_a_resource_eh(self):
                return 'Lain Supe'

            @provide
            @alias('name', 'really_long_name_for_a_resource_eh')
            def person_name(self, name):
                return name

        @alias('birth_name', 'person_name')
        class ModuleB:
            @provide
            def special_name(self, birth_name):
                return 'Her Majesty Princess ' + birth_name

        injector = Injector(ModuleA(), ModuleB())
        name = injector.require('person_name')
        self.assertEqual(name, 'Lain Supe')
        special_name = injector.require('special_name')
        self.assertTrue(special_name, 'Her Majesty Princess Lain Supe')

    def test_bad_alias_loop(self):
        class ModuleA:
            @provide
            def name(self):
                return 'Lain Supe'

            @provide
            @alias('full_name', 'name')
            @alias('name', 'full_name')
            def person_name(self, full_name):
                return full_name

        injector = Injector(ModuleA())
        with self.assertRaises(InjectionError) as context:
            injector.require('person_name')
        self.assertTrue(str(context.exception).startswith('Alias loop detected'))

#--------------------------------------------------------------------
if __name__ == '__main__':
    unittest.main()


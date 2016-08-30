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

#--------------------------------------------------------------------
if __name__ == '__main__':
    unittest.main()


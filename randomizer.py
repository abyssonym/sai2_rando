from randomtools.tablereader import (
    TableObject, get_global_label, tblpath, addresses, get_random_degree,
    get_activated_patches, mutate_normal, shuffle_normal, write_patch)
from randomtools.utils import (
    classproperty, cached_property, get_snes_palette_transformer,
    read_multi, write_multi, utilrandom as random)
from randomtools.interface import (
    get_outfile, get_seed, get_flags, get_activated_codes, activate_code,
    run_interface, rewrite_snes_meta, clean_and_write, finish_interface)
from randomtools.itemrouter import ItemRouter
from collections import defaultdict
from os import path
from time import time, sleep, gmtime
from collections import Counter
from itertools import combinations


VERSION = 1


def route_items():
    ir = ItemRouter(path.join(tblpath, "requirements.txt"),
                    path.join(tblpath, "restrictions.txt"))
    ir.assign_everything()


if __name__ == "__main__":
    try:
        print ("You are using the Super Adventure Island II "
               "randomizer version %s." % VERSION)
        print

        ALL_OBJECTS = [g for g in globals().values()
                       if isinstance(g, type) and issubclass(g, TableObject)
                       and g not in [TableObject]]

        codes = {}

        run_interface(ALL_OBJECTS, snes=True, codes=codes, custom_degree=True)

        f = open(get_outfile(), 'r+b')
        f.seek(addresses.bonus_item_address)
        write_multi(f, 0x44d, length=2)
        f.close()

        route_items()

        clean_and_write(ALL_OBJECTS)
        rewrite_snes_meta("SAI2-R", VERSION, lorom=False)

        finish_interface()

    except Exception, e:
        print "ERROR: %s" % e
        raw_input("Press Enter to close this program.")

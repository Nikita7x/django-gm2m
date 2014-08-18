from collections import defaultdict

import django
from django.db import router
from django.db.models import Manager, Q
from django.utils import six

from .query import GM2MQuerySet
from .models import CT_ATTNAME, PK_ATTNAME
from .helpers import get_content_type, get_model_name


def create_gm2m_related_manager():
    """
    Dynamically create a manager class that only concerns an instance
    """
    class GM2MManager(Manager):
        def __init__(self, instance, through):
            super(GM2MManager, self).__init__()

            self.instance = instance
            self._fk_val = instance.pk

            self.src_field_name = get_model_name(self.instance.__class__)

            self.through = through
            self.core_filters = {'%s_id' % self.src_field_name: instance.pk}

        def get_queryset(self):
            try:
                return self.instance \
                           ._prefetched_objects_cache[self.prefetch_cache_name]
            except (AttributeError, KeyError):
                return GM2MQuerySet(self.through)._next_is_sticky() \
                                                 .filter(**self.core_filters)
        if django.VERSION < (1, 6):
            get_query_set = get_queryset

        def add(self, *objs):
            """
            Adds objects to the GM2M field
            """
            # *objs - object instances to add

            if not objs:
                return

            # sorting by content type to rationalise the number of queries
            ct_pks = defaultdict(lambda: set())
            for obj in objs:
                # Convert the obj to (content_type, primary_key)
                obj_ct = get_content_type(obj)
                obj_pk = obj.pk
                ct_pks[obj_ct].add(obj_pk)

            db = router.db_for_write(self.through, instance=self.instance)
            vals = self.through._default_manager.using(db) \
                                 .values_list(CT_ATTNAME, PK_ATTNAME) \
                                 .filter(**{self.src_field_name: self._fk_val})
            to_add = []
            for ct, pks in six.iteritems(ct_pks):
                ctvals = vals.filter(**{'%s__exact' % CT_ATTNAME: ct.pk,
                                        '%s__in' % PK_ATTNAME: pks})
                for pk in pks.difference(ctvals):
                    to_add.append(self.through(**{
                        '%s_id' % self.src_field_name: self._fk_val,
                        CT_ATTNAME: ct,
                        PK_ATTNAME: pk
                    }))
            # Add the new entries in the db table
            self.through._default_manager.using(db).bulk_create(to_add)
        add.alters_data = True

        def remove(self, *objs):
            """
            Removes objects from the GM2M field
            """
            # *objs - objects to remove

            if not objs:
                return

            # sorting by content type to rationalise the number of queries
            q = Q()
            for obj in objs:
                # Convert the obj to (content_type, primary_key)
                q = q | Q(**{
                    CT_ATTNAME: get_content_type(obj),
                    PK_ATTNAME: obj.pk
                })

            db = router.db_for_write(self.through, instance=self.instance)
            self.through._default_manager.using(db).filter(**{
                '%s_id' % self.src_field_name: self._fk_val
            }).filter(q).delete()
        remove.alters_data = True

        def clear(self):
            db = router.db_for_write(self.through, instance=self.instance)
            self.through._default_manager.using(db).filter(**{
                '%s_id' % self.src_field_name: self._fk_val
            }).delete()
        clear.alters_data = True

    return GM2MManager

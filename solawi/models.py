#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core import validators
from django.db import models
from django.db.models.signals import post_save
from django.core.exceptions import ObjectDoesNotExist
from django.dispatch import receiver
from solawi.validators import *
from django.utils.translation import ugettext_lazy as _
import json
from solawi import utils

class User(AbstractUser):
    ''' '''
    # probably change this field into member since/ next order after vecation
    is_member = models.BooleanField(_('Make a paying member'), default=True)
    is_supervisor = models.BooleanField(_('Make a depot supervisor'),
                                        default=False)

    depot = models.ForeignKey('Depot', on_delete=models.PROTECT,
                              related_name='members', blank=False, null=True)

    countshares = models.IntegerField(blank=False,
                                      default=1,
                                      validators=[validators.MinValueValidator(0)])

    defaultbasket = models.ForeignKey('DefaultBasket',
                                      blank=False,
                                      null=True,
                                      on_delete=models.PROTECT)

    assets = models.IntegerField(blank=False, default=0,
                                 validators=[validators.MinValueValidator(0),
                                             validators.MaxValueValidator(settings.MAX_USER_ASSET)])


    class Meta:
        ''' '''
        verbose_name = _('user')
        verbose_name_plural = _('users')

    def __str__(self):
        if self.first_name == '' and self.last_name == '':
            name = self.username
        else:
            name = self.first_name + ' ' + self.last_name
        if self.depot is None:
            return _('{name}').format(name=name)
        else:
            return _('{name} ({depot})').format(name=name,
                                                depot=self.depot.name)

    def clean(self):
        ''' '''
        if self.is_supervisor:
            if self.depot is None:
                raise ValidationError(_('A Member has to have an depot.'))
        if self.is_member:
            if self.depot is None:
                raise ValidationError(_('A Member has to have an depot.'))
        if self.defaultbasket is None:
            raise ValidationError(_('A Member has to have an '
                                    'weekly basket.'))
        if self.assets > settings.MaxValueValidator:
            self.assets = settings.MaxValueValidator
            self.save()


class ProductProperty(models.Model):
    product = models.ForeignKey('Product',
                                on_delete=models.CASCADE,
                                related_name='properties',
                                blank=False)

    orderable = models.BooleanField(default=True)

    packagesize = models.FloatField(default=1)
    producttype = models.CharField(max_length=15,
                                   default='',
                                   blank=True,
                                   help_text=_('product type'))

    max_at_once = models.IntegerField(help_text=_('max amount orderable at once'),
                                      blank=False,
                                      default=5)

    @property
    def exchange_value(self):
        return product.exchange_value*packagesize

    def __str__(self):
        return _('{packagesize} {unit} of {producttype} {product}').format(
            product=self.product,
            producttype=self.producttype,
            packagesize=self.packagesize,
            unit=self.product.unit)

    class Meta:
        verbose_name = _('properties of product')
        verbose_name_plural = _('properties of products')
        unique_together = ('product', 'producttype', 'packagesize')


class Product(models.Model):
    ''' '''
    name = models.CharField(max_length=30, unique=True)
    orderable = models.BooleanField(default=True)

    unit = models.CharField(max_length=15, default='',
                            help_text=_('measuring unit,'
                                        'e.g. kg or L'))

    # default value none means not modular the time am regular order many not
    # be changed
    module_time = models.IntegerField(help_text=_('module duration in weeks'),
                                      blank=True,
                                      null=True)
    price_of_module = models.FloatField(help_text=_('modular product price'),
                                        blank=True,
                                        null=True)

    # default 0 means not exchangable or better you woun't get anything for it
    exchange_value = models.FloatField(null=True,
                                       default=0,
                                       validators=[validators.MinValueValidator(0)],
                                       help_text=_('exchange value per unit'))

    class Meta:
        ''' '''
        verbose_name = _('product')
        verbose_name_plural = _('products')

    def __str__(self):
        return _('{name}').format(name=self.name)


class Depot(models.Model):
    ''' '''
    name = models.CharField(max_length=30, unique=True)
    location = models.CharField(max_length=30, default='')

    class Meta:
        ''' '''
        verbose_name = _('depot')
        verbose_name_plural = _('depots')

    def __str__(self):
        return _('{name} at {location}').format(name=self.name,
                                                location=self.location)


class Amount(models.Model):
    '''Intermediate model for OrderContent and Productproperty.
    
    Prefetch_related productproperty and productproperty__product if you use
    the @properties'''

    productproperty = models.ForeignKey('ProductProperty',
                                        related_name='amount',
                                        on_delete=models.PROTECT,
                                        blank=False)
    count = models.IntegerField(default=1,
                                validators = [ validators.MinValueValidator(1) ]
                                )

    ordercontent = models.ForeignKey('OrderContent',
                                      related_name='contains',
                                      on_delete=models.CASCADE,
                                      blank=False)

    @property
    def exchange_value(self):
        return self.count*self.productproperty.exchange_value
    
    def clean(self):
        productp = self.productproperty
        if count > productp.max_at_once/productp.packagesize: 
            raise ValidationError(_('You can not order more then {max} of'
                '{product} at onces ').format(maxx = productp.max_at_once, product=productp))

    class Meta:
        ''' '''
        verbose_name = _('packed product')
        verbose_name_plural = _('packed products')
        # uniqueness for productproperty to map e.g. flour or oat flakes types
        unique_together = ('ordercontent' ,'productproperty')

    def __str__(self):
        return '{count}'.format(
            count=self.count, pro=self.productproperty,
            ordr=self.ordercontent)


class OrderContent(models.Model):
    ''' '''
    productproperties = models.ManyToManyField('ProductProperty',
                                      through='Amount',
                                      related_name='isin',
                                      blank=False)

    def add_or_create_product(self, prdctprop, count=1):
        '''Add count or create productproperty for ordercontent.

        defaults count=1 
        returns: amount.exchange_value , created'''
        amount, created = Amount.objects.get_or_create(
                productproperty=prdctprop, 
                ordercontent=self,
                defaults={'count': count})

        if not created:
            amount.count += count
            amount.save()

        return amount.exchange_value, created

    def sub_or_delete_product(self, prdctprop, count=None):
        '''Subtract count or delete productproperty form ordercontent.

        defaults count=None deleates product
            returns: (min(amount.echange_value, prdctprop.exchange_value) , persists) of amount'''
        try:
            amount = Amount.objects.get(productproperty=prdctprop, 
                                        ordercontent=present.content)
            value = amount.exchange_value

            if amount.count > count:
                amount.count -= count
                amount.save()
                return prdctprop.exchange_value, True
            else:
                amount.delete()
                return value, False

        except Amount.DoesNotExist:
            # No Product -> no value
            return 0, False

    class Meta:
        verbose_name = _('content of order')
        verbose_name_plural = _('content of orders')

    def __str__(self):
        ostr = ', '.join([str(i.product)[:3] for i
            in self.productproperties.all()])
        return _('{order} (ID: {id}) ').format(order=ostr, id=self.id)
        # return _('{order} ').format(order=self.id)


class DefaultBasket(models.Model):
    ''' '''
    content = models.OneToOneField('OrderContent',
                                   blank=False,
                                   null=True,
                                   parent_link=True,
                                   on_delete=models.PROTECT,
                                   related_name='defaultbaskets')

    name = models.CharField(max_length=15,
                            blank=False,
                            unique=True,
                            default='',
                            help_text=_('basket name'))

    class Meta:
        verbose_name = _('default orderbasket')
        verbose_name_plural = _('default orderbaskets')

    def __str__(self):
        return _('Default Order: {name}').format(name=self.name,
                                                 order=self.content)


class OrderBasket(models.Model):
    ''' .'''
    content = models.OneToOneField('OrderContent',
                                   blank=False,
                                   null=True,
                                   parent_link=True,
                                   on_delete=models.PROTECT,
                                   related_name='order')

    week = models.DateField(blank=False,
                            null=True)

    user = models.ForeignKey('User',
                             on_delete=models.CASCADE,
                             related_name='orderbaskets',
                             blank=False,
                             null=True)

    def add_to_order(self, prdctprop, count=1, account=True):
        '''Add a product to order.'''
        value = prdctprop.exchange_value*count

        if not (prdctprop.orderable and prdctprop.product.orderable):
            raise ValidationError(_('%(prdctprop)s is not orderable'),
                                    params={'prdctprop': prdctprop},
                                    code='notorderable')
                                    # TODO Maybe pass why not orderable

        elif account:
            if self.user.assets < value:
                raise ValidationError(_('%(user)s assets where to low to order %(count)s %(prdctprop)s'),
                                        params={'prdctprop': prdctprop,
                                                'count': count,
                                                'prdctprop': prdctprop},
                                        code='notorderable')

            else:
                value, created = self.content.add_or_create_product(prdctprop, count)

                self.user.assets -= value
                self.user.save()
        else:
            self.content.add_or_create_product(prdctprop, count)

    def sub_from_order(self, prdctprop, count=None, account=True):
        '''Subtract or delete a product from order.'''

        value, persists = self.content.sub_or_delete_product(prdctprop, count)

        if not persits and value == 0:
            raise ValidationError(_('%(prdctprop)s was not ordered'),
                                    params={'prdctprop': productproperty},
                                    code='notordered')
        elif account and value > 0:
            self.user.assets += value
            self.user.clean()
            self.user.save()

    def clean(self):
        ''' .'''
        self.week = utils.get_monday(self.week)
        self.save()

        # TODO kick product out of OrderContent if not oderable (in product an
        # productproperties!) or don't and assert that only orderable product
        # for this week are taken into account

    # TODO replace get_moday with get packing day and do this for all other
    # contents aswell
    def save(self, *args, **kwargs):
        ''' .'''
        # Set every date on Monday!
        self.week = utils.get_monday(self.week)
        super(OrderBasket, self).save(*args, **kwargs)

    class Meta:
        ''' .'''
        verbose_name = _('ordering basket')
        verbose_name_plural = _('ordering baskets')
        unique_together = ('week', 'user')

    def __str__(self):
        return _('{week} by {user}').format(
            week=self.week.strftime('%Y-%W'), user=self.user)


class RegularyOrder(models.Model):

    user = models.ForeignKey('User',
                             on_delete=models.CASCADE,
                             related_name='regularyorders',
                             blank=False,
                             null=True)

    productproperty = models.ForeignKey('ProductProperty',
                                        on_delete=models.PROTECT)
    count = models.IntegerField(default=0) 

    #savings = models.FloatField(default=0,
    #                            null=True) # TODO validate

    # period the user wants to order in
    # indicates conterOrder if negative see property is_counterorder
    period = models.IntegerField(default=1) # TODO validate via
    #approx_next_order or the current counterorder share

    # if modular product lastorder = last changing time!
    lastorder = models.DateField()

    lastaccses = models.DateField(auto_now=True)

    @property
    def is_counterorder(self):
        '''True if is self is counterorder else order.'''
        return self.period <= 0

    @property
    def exchange_value(self):
        return self.count*self.productproperty.exchange_value

    @property
    def ready(self):
        '''.'''
        return self.lastorder+datetime.timedelta(weeks=self.period-1)<utils.this_week()

    @property
    def orderable(self):
        return (self.productproperty.orderable and
                self.productproperty.product.orderable)

#    def current_counterorder_share(self, regords=None):
#        # TODO test if summ of all current counterorder shares is one!
#        if regords == None:
#            regord = self.user.regularyorders.objects.all().prefetch_related('productproperty__product')
#
#        evSum, regSumPeriod = 0, 0
#        for reg in regords:
#            evSum += reg.exchange_value
#            regSumPeriod += reg.period()
#
#        return (self.exchange_value/self.period)*(evSum/regSumPeriod)
#
#    # TODO changingtime for modular validate savings = None if
#    # about productproperty.product.modular =True
#    def approx_next_order(self):
#        if self.ready():
#            return _('surely'), self.lastorder+datetime.timedelta(weeks=self.period)
#        else:
#            # TODO Send warning not enough counterorder
#            # calculate current counterorder share
#            cc = current_counterorder_share()*sum([ amount.exchange_value for amount in
#                self.user.counterorder.contains.all()])
#
#            # needs to be saved
#            rest = (savings - self.exchange_value)
#            # approx weeks left till order
#            # round integer up without import any math
#            left = (rest // ccs + (rest % ccs > 0))
#            if left > 3*self.period:
#                # TODO Document behavior or just send warning or raise
#                # Validation Error
#                return _('never'), None
#            elif:
#                return _('longer than wished'), self.lastorder+datetime.timedelta(weeks=left)
#            else: 
#                return _('approximately'), self.lastorder+datetime.timedelta(weeks=left)



    class Meta:
        ''' '''
        verbose_name = _('regularly order')
        verbose_name_plural = _('regularly orders')
        unique_together = ('user', 'productproperty')

    def __str__(self):
        return _('{user} regularly orders: {count}x{product}').format(user=self.user,
                                                                      product=self.productproperty,
                                                                      count=self.count)

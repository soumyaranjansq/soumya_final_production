# from django.shortcuts import render, get_object_or_404, redirect
# from django.contrib.auth.decorators import login_required
# from django.contrib import messages
# from django.forms import modelformset_factory

# from accounts.decorators import role_required, hospital_required
# from .models import Hospital, Bill, BillDocument, BillItem, Service, Scheme
# from .forms import BillForm, BillDocumentForm, BillItemForm
# from workflow.models import SanctionRequest, WorkflowStep


# @login_required
# @hospital_required
# def hospital_dashboard(request):
#     """Dashboard for hospital users."""
#     try:
#         hospital = request.user.profile.hospital
#     except AttributeError:
#         messages.error(request, 'No hospital assigned to your account.')
#         return redirect('dashboard')
    
#     bills = Bill.objects.filter(hospital=hospital).order_by('-created_at')[:20]
    
#     return render(request, 'hospitals/dashboard.html', {
#         'hospital': hospital,
#         'bills': bills,
#     })


# @login_required
# @hospital_required
# def submit_bill(request):
#     """View to handle new bill submission with items and amounts."""
#     hospital = request.user.profile.hospital
    
#     # Create a formset for bill items (Service + Amount)
#     BillItemFormSet = modelformset_factory(
#         BillItem, 
#         form=BillItemForm, 
#         extra=0,
#         can_delete=False
#     )
    
#     services = Service.objects.filter(is_active=True)
    
#     if request.method == 'POST':
#         bill_form = BillForm(request.POST, request.FILES)
#         formset = BillItemFormSet(request.POST, request.FILES, queryset=BillItem.objects.none())
        
#         if bill_form.is_valid() and formset.is_valid():
#             bill = bill_form.save(commit=False)
#             bill.hospital = hospital
#             bill.created_by = request.user
#             bill.status = 'SUBMITTED'
#             bill.save()
            
#             # Save items and calculate gross total
#             total_amount = 0
#             print(f"DEBUG: Processing {len(formset)} forms")
#             for i, form in enumerate(formset):
#                 # Process if Service FK is selected OR if a Custom Name is entered (with amounts)
#                 # Note: form.cleaned_data might rely on prefix names in template
#                 if form.cleaned_data.get('service') or form.cleaned_data.get('hospital_service_name'):
#                     item = form.save(commit=False)
#                     item.bill = bill
                    
#                     # Ensure name is captured. If FK exists, use its name as fallback if custom name empty
#                     if item.service and not item.hospital_service_name:
#                         item.hospital_service_name = item.service.name
                    
#                     # DEBUG: Print Item Data
#                     print(f"DEBUG item {i}: Rate={item.claimed_rate}, Qty={item.claimed_quantity}, AmountInput={item.claimed_amount}")
                    
#                     item.save()  # Model's save() handles calculation if amount is missing
                    
#                     print(f"DEBUG item {i} Saved: Amount={item.claimed_amount}")
                    
#                     total_amount += item.claimed_amount
            
#             print(f"DEBUG: Total Amount Calculated: {total_amount}")
            
#             # Update bill with calculated total
#             bill.gross_claimed_amount = total_amount
#             bill.save()
            
#             # Create SanctionRequest to enter workflow
#             first_step = WorkflowStep.objects.order_by('order').first()
#             SanctionRequest.objects.create(
#                 bill=bill,
#                 hospital_name=hospital.name,
#                 patient_name=bill.patient_name,
#                 claimed_amount=bill.gross_claimed_amount,
#                 current_step=first_step,
#                 status='PENDING'
#             )
            
#             messages.success(request, 'Bill submitted successfully and entered the approval workflow!')
#             return redirect('hospitals:dashboard')
#         else:
#             messages.error(request, 'Please correct the errors below.')
#     else:
#         bill_form = BillForm()
#         bill_form.fields['scheme'].queryset = Scheme.objects.filter(is_active=True)
#         formset = BillItemFormSet(queryset=BillItem.objects.none())
        
#     return render(request, 'hospitals/submit_bill.html', {
#         'bill_form': bill_form,
#         'formset': formset,
#         'services': services,
#     })


# @login_required
# @hospital_required
# def bill_list(request):
#     """List all bills for the hospital."""
#     try:
#         hospital = request.user.profile.hospital
#     except AttributeError:
#         messages.error(request, 'No hospital assigned to your account.')
#         return redirect('dashboard')
    
#     bills = Bill.objects.filter(hospital=hospital).order_by('-created_at')
    
#     return render(request, 'hospitals/bill_list.html', {
#         'hospital': hospital,
#         'bills': bills,
#     })


# @login_required
# def bill_detail(request, bill_id):
#     """View bill details with documents."""
#     bill = get_object_or_404(Bill, id=bill_id)
    
#     # Check access permissions
#     profile = request.user.profile
#     if profile.role == 'HOSPITAL':
#         if profile.hospital != bill.hospital:
#             messages.error(request, 'Access denied.')
#             return redirect('dashboard')
    
#     documents = bill.documents.all()
    
#     return render(request, 'hospitals/bill_detail.html', {
#         'bill': bill,
#         'documents': documents,
#     })
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction

from accounts.decorators import role_required, hospital_required
from .models import Hospital, Bill, BillDocument, BillItem, Service, Scheme
from .forms import BillForm, BillDocumentForm
from workflow.models import SanctionRequest, WorkflowStep


@login_required
@hospital_required
def hospital_dashboard(request):
    """Dashboard for hospital users."""
    try:
        hospital = request.user.profile.hospital
        if not hospital:
            messages.error(request, 'No hospital assigned to your account. Please contact administrator.')
            return redirect('dashboard')
    except AttributeError:
        messages.error(request, 'No hospital assigned to your account.')
        return redirect('dashboard')
    
    bills = Bill.objects.filter(hospital=hospital).order_by('-created_at')[:20]
    
    # Calculate statistics
    total_bills = Bill.objects.filter(hospital=hospital).count()
    approved_bills = Bill.objects.filter(hospital=hospital, status='APPROVED').count()
    pending_bills = Bill.objects.filter(hospital=hospital, status__in=['SUBMITTED', 'UNDER_REVIEW']).count()
    rejected_bills = Bill.objects.filter(hospital=hospital, status='REJECTED').count()
    
    return render(request, 'hospitals/dashboard.html', {
        'hospital': hospital,
        'bills': bills,
        'total_bills': total_bills,
        'approved_bills': approved_bills,
        'pending_bills': pending_bills,
        'rejected_bills': rejected_bills,
    })


@login_required
@hospital_required
def submit_bill(request):
    """View to handle new bill submission with array-based form data."""
    try:
        hospital = request.user.profile.hospital
        if not hospital:
            messages.error(request, 'No hospital assigned to your account. Please contact administrator.')
            return redirect('hospitals:dashboard')
    except AttributeError:
        messages.error(request, 'No hospital assigned to your account.')
        return redirect('dashboard')
    
    services = Service.objects.filter(is_active=True)
    
    if request.method == 'POST':
        bill_form = BillForm(request.POST, request.FILES)
        
        # Get array data from POST
        service_categories = request.POST.getlist('service_category[]')
        hospital_service_names = request.POST.getlist('hospital_service_name[]')
        service_ids = request.POST.getlist('service[]')
        claimed_rates = request.POST.getlist('claimed_rate[]')
        claimed_quantities = request.POST.getlist('claimed_quantity[]')
        claimed_amounts = request.POST.getlist('claimed_amount[]')
        supporting_documents = request.FILES.getlist('supporting_document[]')
        comments_list = request.POST.getlist('comments[]')
        
        # Debug logging
        print(f"DEBUG - Service Categories: {service_categories}")
        print(f"DEBUG - Service Names: {hospital_service_names}")
        print(f"DEBUG - Rates: {claimed_rates}")
        print(f"DEBUG - Quantities: {claimed_quantities}")
        
        # Validate that we have at least one item
        if not service_categories or len(service_categories) == 0:
            messages.error(request, 'Please add at least one service item.')
            bill_form.fields['scheme'].queryset = Scheme.objects.filter(is_active=True)
            return render(request, 'hospitals/submit_bill.html', {
                'bill_form': bill_form,
                'services': services,
            })
        
        # Validate bill form
        if bill_form.is_valid():
            try:
                with transaction.atomic():
                    # Save bill
                    bill = bill_form.save(commit=False)
                    bill.hospital = hospital
                    bill.created_by = request.user
                    bill.status = 'SUBMITTED'
                    
                    # Debug: Print bill data before save
                    print(f"DEBUG - Bill Patient Name: {bill.patient_name}")
                    print(f"DEBUG - Bill Employee ID: {bill.employee_id}")
                    
                    bill.save()
                    
                    print(f"DEBUG - Bill saved with ID: {bill.id}, Claim ID: {bill.claim_id}")
                    
                    # Process and save items
                    total_amount = 0
                    items_saved = 0
                    
                    for i in range(len(service_categories)):
                        # Skip empty rows
                        if not service_categories[i] or not hospital_service_names[i]:
                            print(f"DEBUG - Skipping empty row {i}")
                            continue
                        
                        try:
                            # Get values with defaults
                            rate = float(claimed_rates[i]) if i < len(claimed_rates) and claimed_rates[i] else 0
                            qty = int(claimed_quantities[i]) if i < len(claimed_quantities) and claimed_quantities[i] else 1
                            amount = float(claimed_amounts[i]) if i < len(claimed_amounts) and claimed_amounts[i] else (rate * qty)
                            
                            print(f"DEBUG - Item {i}: Rate={rate}, Qty={qty}, Amount={amount}")
                            
                            # Get service if selected
                            service = None
                            if i < len(service_ids) and service_ids[i]:
                                try:
                                    service = Service.objects.get(id=service_ids[i])
                                except Service.DoesNotExist:
                                    pass
                            
                            # Get supporting document if provided
                            supporting_doc = None
                            if i < len(supporting_documents):
                                supporting_doc = supporting_documents[i]
                            
                            # Get comments
                            comments = ''
                            if i < len(comments_list):
                                comments = comments_list[i]
                            
                            # Create bill item
                            bill_item = BillItem.objects.create(
                                bill=bill,
                                service=service,
                                hospital_service_name=hospital_service_names[i],
                                claimed_rate=rate,
                                claimed_quantity=qty,
                                claimed_amount=amount,
                                supporting_document=supporting_doc,
                                comments=comments,
                                description=f"Category: {service_categories[i]}"
                            )
                            
                            print(f"DEBUG - BillItem {bill_item.id} created successfully")
                            
                            total_amount += amount
                            items_saved += 1
                            
                        except (ValueError, IndexError) as e:
                            print(f"ERROR - Processing item {i}: {e}")
                            continue
                    
                    # Validate that at least one item was saved
                    if items_saved == 0:
                        raise ValueError("No valid service items were processed. Please check your input.")
                    
                    # Update bill with total amount
                    bill.gross_claimed_amount = total_amount
                    bill.save()
                    
                    print(f"DEBUG - Bill updated with total amount: {total_amount}")
                    
                    # Create SanctionRequest to enter workflow
                    first_step = WorkflowStep.objects.order_by('order').first()
                    if not first_step:
                        raise ValueError("No workflow steps configured. Please contact administrator.")
                    
                    # Use correct field name based on your Hospital model
                    hospital_name = hospital.name if hasattr(hospital, 'name') else hospital.hospital_name
                    
                    sanction_request = SanctionRequest.objects.create(
                        bill=bill,
                        hospital_name=hospital_name,
                        patient_name=bill.patient_name,
                        claimed_amount=bill.gross_claimed_amount,
                        current_step=first_step,
                        status='PENDING'
                    )
                    
                    print(f"DEBUG - SanctionRequest {sanction_request.id} created")
                    
                    messages.success(
                        request, 
                        f'✓ Claim submitted successfully! '
                        f'Claim ID: {bill.claim_id} | '
                        f'Items: {items_saved} | '
                        f'Total: ₹{total_amount:,.2f}'
                    )
                    return redirect('hospitals:dashboard')
                    
            except ValueError as e:
                messages.error(request, f'Error: {str(e)}')
                print(f"ERROR - ValueError: {e}")
            except Exception as e:
                messages.error(request, f'An unexpected error occurred. Please try again or contact support.')
                print(f"ERROR - Exception in submit_bill: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
        else:
            # Form validation errors
            print(f"DEBUG - Form errors: {bill_form.errors}")
            for field, errors in bill_form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        bill_form = BillForm()
        bill_form.fields['scheme'].queryset = Scheme.objects.filter(is_active=True)
    
    return render(request, 'hospitals/submit_bill.html', {
        'bill_form': bill_form,
        'services': services,
        'hospital': hospital,  # Pass hospital to template
    })


@login_required
@hospital_required
def bill_list(request):
    """List all bills for the hospital."""
    try:
        hospital = request.user.profile.hospital
        if not hospital:
            messages.error(request, 'No hospital assigned to your account.')
            return redirect('dashboard')
    except AttributeError:
        messages.error(request, 'No hospital assigned to your account.')
        return redirect('dashboard')
    
    bills = Bill.objects.filter(hospital=hospital).order_by('-created_at')
    
    # Apply filters if provided
    status = request.GET.get('status')
    employee_id = request.GET.get('employee_id')
    patient_name = request.GET.get('patient_name')
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    if status:
        bills = bills.filter(status=status)
    if employee_id:
        bills = bills.filter(employee_id__icontains=employee_id)
    if patient_name:
        bills = bills.filter(patient_name__icontains=patient_name)
    if from_date:
        bills = bills.filter(submitted_at__gte=from_date)
    if to_date:
        bills = bills.filter(submitted_at__lte=to_date)
    
    return render(request, 'hospitals/bill_list.html', {
        'hospital': hospital,
        'bills': bills,
    })


@login_required
def bill_detail(request, bill_id):
    """View bill details with documents."""
    bill = get_object_or_404(Bill, id=bill_id)
    
    # Check access permissions
    profile = request.user.profile
    if profile.role == 'HOSPITAL':
        if profile.hospital != bill.hospital:
            messages.error(request, 'Access denied.')
            return redirect('dashboard')
    
    documents = bill.documents.all()
    
    return render(request, 'hospitals/bill_detail.html', {
        'bill': bill,
        'documents': documents,
    })
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument
uiapp = DocumentManager.Instance.CurrentUIApplication
app = uiapp.Application

# Inputs
rooms = UnwrapElement(IN[0])  # List of Room elements
names = IN[1]  # List of names (can be None)

filled_regions = []
simple_errors = []

# Basic info
basic_info = {
    "total_rooms": len(rooms) if rooms else 0,
    "active_view": doc.ActiveView.Name if doc and doc.ActiveView else "No active view",
    "view_type": str(doc.ActiveView.ViewType) if doc and doc.ActiveView else "Unknown"
}

TransactionManager.Instance.EnsureInTransaction(doc)

for i, room in enumerate(rooms):
    room_name = names[i] if i < len(names) and names[i] else f"Room_{i}"
    
    try:
        # Basic validation
        if room is None:
            simple_errors.append(f"{room_name}: Room is null")
            continue
            
        if not isinstance(room, SpatialElement):
            simple_errors.append(f"{room_name}: Not a SpatialElement")
            continue
        
        # Check if room is placed and has area
        if room.Location is None:
            simple_errors.append(f"{room_name}: Room is not placed")
            continue
            
        if room.Area <= 0:
            simple_errors.append(f"{room_name}: Room has zero area")
            continue
        
        # Alternative approach: Use room boundaries with different options
        options = SpatialElementBoundaryOptions()
        options.SpatialElementBoundaryLocation = SpatialElementBoundaryLocation.Finish
        options.StoreFreeBoundaryFaces = True
        
        # Try different boundary location options if first one fails
        boundary_options = [
            SpatialElementBoundaryLocation.Finish,
            SpatialElementBoundaryLocation.Center,
            SpatialElementBoundaryLocation.CoreBoundary,
            SpatialElementBoundaryLocation.CoreCenter
        ]
        
        curve_loop = None
        successful_option = None
        
        for boundary_location in boundary_options:
            try:
                options.SpatialElementBoundaryLocation = boundary_location
                boundaries = room.GetBoundarySegments(options)
                
                if not boundaries or len(boundaries) == 0:
                    continue
                
                # Process the first (outer) boundary
                first_loop = boundaries[0]
                if len(first_loop) == 0:
                    continue
                
                # Get all curves
                all_curves = []
                for segment in first_loop:
                    curve = segment.GetCurve()
                    if curve is not None and curve.Length > 0.001:  # Very small minimum
                        all_curves.append(curve)
                
                if len(all_curves) < 3:  # Need at least 3 curves for a loop
                    continue
                
                # Try to create curve loop with original curves
                try:
                    curve_loop = CurveLoop.Create(all_curves)
                    successful_option = boundary_location
                    break
                except:
                    # If that fails, try creating a simplified polygon
                    try:
                        # Get all unique points from the curves
                        points = []
                        for curve in all_curves:
                            start_pt = curve.GetEndPoint(0)
                            end_pt = curve.GetEndPoint(1)
                            
                            # Add start point if not too close to previous points
                            if not points or points[-1].DistanceTo(start_pt) > 0.01:
                                points.append(start_pt)
                        
                        # Remove duplicate points and create simplified boundary
                        if len(points) >= 3:
                            # Create lines between consecutive points
                            simplified_curves = []
                            for j in range(len(points)):
                                start_pt = points[j]
                                end_pt = points[(j + 1) % len(points)]  # Wrap to first point
                                
                                if start_pt.DistanceTo(end_pt) > 0.01:  # Only create if long enough
                                    line = Line.CreateBound(start_pt, end_pt)
                                    simplified_curves.append(line)
                            
                            if len(simplified_curves) >= 3:
                                curve_loop = CurveLoop.Create(simplified_curves)
                                successful_option = f"{boundary_location}_simplified"
                                break
                    except:
                        continue
            except:
                continue
        
        if curve_loop is None:
            simple_errors.append(f"{room_name}: Could not create valid curve loop with any boundary option")
            continue
        
        # Create curve loop list
        curve_loop_list = List[CurveLoop]()
        curve_loop_list.Add(curve_loop)
        
        # Get filled region type
        collector = FilteredElementCollector(doc).OfClass(FilledRegionType)
        filled_region_type = collector.FirstElement()
        
        if filled_region_type is None:
            simple_errors.append(f"{room_name}: No FilledRegionType found")
            continue
        
        # Get active view
        view = doc.ActiveView
        
        # Create filled region
        filled_region = FilledRegion.Create(doc, filled_region_type.Id, view.Id, curve_loop_list)
        
        # Set comment parameter
        param = filled_region.LookupParameter("Comments")
        if param and param.StorageType == StorageType.String:
            param.Set(f"{room_name} ({successful_option})")
        
        filled_regions.append(filled_region)
        
    except Exception as e:
        simple_errors.append(f"{room_name}: Unexpected error - {str(e)}")
        continue

TransactionManager.Instance.TransactionTaskDone()

OUT = [filled_regions, simple_errors, basic_info]
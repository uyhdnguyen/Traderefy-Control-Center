#region Using declarations
using System;
using System.IO;
using System.Threading;
using System.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    // SIM/Playback-only one-shot bridge. Enable manually on the SAME chart/instrument and SIM account.
    public class TraderefyExecutionManager : Strategy
    {
        private static bool IsAllowedTradeSimulationAccount(string name)
        {
            return !string.IsNullOrWhiteSpace(name) &&
                (name.StartsWith("Sim", StringComparison.OrdinalIgnoreCase) ||
                 string.Equals(name, "Playback101", StringComparison.OrdinalIgnoreCase));
        }
        private bool IsPlaybackAccount()
        {
            return Account != null && string.Equals(Account.Name, "Playback101", StringComparison.OrdinalIgnoreCase);
        }
        private string bridgeDir;
        private string commandFile;
        private string autoCommandFile;
        private string autoHeartbeatFile;
        private bool Phase10ExactAccount
        {
            get { return Account!=null && (Account.Name=="SimIBS" || Account.Name=="SimFTR" || IsPlaybackAutoReady()); }
        }
        private string PlaybackFamily
        {
            get {
                if(BarsPeriod==null)return "";
                if(BarsPeriod.BarsPeriodType==NinjaTrader.Data.BarsPeriodType.Minute && BarsPeriod.Value==5)return "IBS";
                if(BarsPeriod.BarsPeriodType==NinjaTrader.Data.BarsPeriodType.Tick && BarsPeriod.Value==699)return "FTR";
                return "";
            }
        }
        private bool IsPlaybackAutoReady()
        {
            if(!IsPlaybackAccount() || PlaybackFamily=="")return false;
            try {
                string p=Path.Combine(NinjaTrader.Core.Globals.UserDataDir,"Traderefy","TUS_Playback_Mode.txt");
                return File.Exists(p) && (File.ReadAllText(p).Trim()=="PLAYBACK" || File.ReadAllText(p).Trim()=="ON");
            } catch{return false;}
        }
        private string AutoKey()
        {
            return Account.Name+"_"+Instrument.FullName.Replace(" ","_").Replace("/","_")+
                (IsPlaybackAccount()?"_"+PlaybackFamily:"");
        }
        // R43: account/instrument/family-scoped diagnostic consumed by TUS status cards.
        private void R43Diagnostic(string code,string detail)
        {
            try {
                if(Account==null || Instrument==null || bridgeDir==null)return;
                string key=AutoKey();
                string path=Path.Combine(bridgeDir,"auto_diagnostic_"+key+".txt");
                File.WriteAllText(path,DateTime.UtcNow.Ticks+"|"+code+"|"+
                    (detail??"").Replace("|","/").Replace("\r"," ").Replace("\n"," "));
                string eventsPath=Path.Combine(bridgeDir,"auto_events_"+key+".log");
                File.AppendAllText(eventsPath,DateTime.UtcNow.ToString("o",System.Globalization.CultureInfo.InvariantCulture)+
                    " | "+code+" | "+(detail??"").Replace("\r"," ").Replace("\n"," ")+Environment.NewLine);
                Print("TUS R44 ["+Account.Name+" "+PlaybackFamily+"] "+code+" "+detail);
            }catch(Exception ex){Print("TUS R43 diagnostic error: "+ex.Message);}
        }
        // R54: read-only, account-scoped FTR trace. Never affects order decisions.
        private void R54Trace(string stage,string commandId,string signalId,string detail)
        {
            try {
                if(bridgeDir==null || Account==null || Instrument==null)return;
                string path=Path.Combine(bridgeDir,"ftr_trace_"+AutoKey()+".log");
                string line=DateTime.UtcNow.ToString("o",System.Globalization.CultureInfo.InvariantCulture)+
                    " | "+stage+" | commandId="+(commandId??"").Replace("|","/")+
                    " signalId="+(signalId??"").Replace("|","/")+" | "+
                    (detail??"").Replace("|","/").Replace("\r"," ").Replace("\n"," ");
                File.AppendAllText(path,line+Environment.NewLine);
            }catch(Exception ex){Print("TUS R54 trace error: "+ex.Message);}
        }
        private string lastId = "";
        private string phase7ActiveCommandId = "";
        private bool phase7TwoLegActive;
        private bool phase7BreakevenMoved;
        private bool phase7AnyEntryFilled;
        private bool phase7CancelRequested;
        private DateTime phase7SubmittedUtc = DateTime.MinValue;
        private int phase7ExpirySeconds;
        private bool phase8IbsEntry;
        private int phase8SignalBar=-1;
        private Order phase7EntryOrder1;
        private Order phase7EntryOrder2;
        private Order phase7RunnerStopOrder;
        private bool phase7Tp1Filled;
        private bool phase7Tp2Filled;
        private bool phase7ExitEmergency;
        private readonly object phase7StatusLock = new object();
        private double phase7EntryPrice;
        private double phase8RunnerFillPrice=double.NaN;
        private double phase7StopPrice;
        private int phase7Direction;
        private string forwardSetup="";
        private string forwardRiskMode="NORMAL";
        private string forwardSignalId="";
        private void WriteForwardFill(Execution execution, double price,int quantity,DateTime time)
        {
            try
            {
                string path=Path.Combine(NinjaTrader.Core.Globals.UserDataDir,"Traderefy","TUS_SIM_Forward_Fills.tsv");
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                File.AppendAllText(path,string.Join("\t",new[]{
                    time.ToString("o",System.Globalization.CultureInfo.InvariantCulture),
                    Account.Name,Instrument.FullName,forwardSetup,forwardRiskMode,
                    forwardSignalId,phase7ActiveCommandId,execution.ExecutionId,
                    quantity.ToString(System.Globalization.CultureInfo.InvariantCulture),
                    price.ToString("R",System.Globalization.CultureInfo.InvariantCulture),
                    phase7StopPrice.ToString("R",System.Globalization.CultureInfo.InvariantCulture)
                })+Environment.NewLine);
            }
            catch(Exception ex){Print("TUS SIM fill audit: "+ex.Message);}
        }
        private const string Phase7Leg1 = "TUS_P7_TP1";
        private const string Phase7Leg2 = "TUS_P7_TP2";
        private DateTime lastCheck = DateTime.MinValue;
        private Timer heartbeatTimer;
        private string heartbeatFile;
        private string accountHeartbeatFile;
        private string managementFile;
        private string lastManagementId = "";
        private string statusFile;
        private string scopedStatusFile;
        private double phase8InvalidationPrice=double.NaN;
        private double r51FtrExtensionPrice=double.NaN;
        private DateTime r51FtrSwingTime=DateTime.MinValue;
        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        [System.ComponentModel.DataAnnotations.Range(0.1,10.0)]
        [System.ComponentModel.DataAnnotations.Display(Name="FTR pending extension (ATR)",GroupName="Trade Control Settings",Order=50)]
        public double FtrPendingAtrMultiple {get;set;}
        [NinjaTrader.NinjaScript.NinjaScriptProperty]
        [System.ComponentModel.DataAnnotations.Range(1,240)]
        [System.ComponentModel.DataAnnotations.Display(Name="FTR pending market cycle (minutes)",GroupName="Trade Control Settings",Order=51)]
        public int FtrPendingCycleMinutes {get;set;}
        private void PublishOrderState(string status, string details)
        {
            try
            {
                if (string.IsNullOrEmpty(statusFile) || Account==null || Instrument==null) return;
                lock (phase7StatusLock)
                {
                    string payload=DateTime.UtcNow.Ticks+"|"+Account.Name+"|"+
                        Instrument.FullName+"|"+status+"|"+(details??"").Replace("|","/");
                    // R10: all TEM instances share order_status.txt. Use the same process-wide
                    // lock and guaranteed .tmp cleanup as the heartbeat writer, and also publish
                    // the account/instrument-scoped file that TCC reads per TEM instance.
                    if(!string.IsNullOrEmpty(scopedStatusFile))
                        WriteHeartbeatAtomic(scopedStatusFile,payload);
                    WriteHeartbeatAtomic(statusFile,payload);
                }
            }
            catch(Exception ex){Print("TUS SIM status write: "+ex.Message);}
        }
        protected override void OnOrderUpdate(Order order, double limitPrice, double stopPrice,
            int quantity, int filled, double averageFillPrice, OrderState orderState,
            DateTime time, ErrorCode error, string comment)
        {
            if(State!=State.Realtime || order==null)return;
            if (phase7TwoLegActive)
            {
                if (order.Name == Phase7Leg1 && order.OrderAction == (phase7Direction>0 ? OrderAction.Buy : OrderAction.SellShort))
                    phase7EntryOrder1=order;
                if (order.Name == Phase7Leg2 && order.OrderAction == (phase7Direction>0 ? OrderAction.Buy : OrderAction.SellShort))
                    phase7EntryOrder2=order;
                // Rejecting one entry while the other remains working creates an unintended one-leg trade.
                if ((order.Name==Phase7Leg1 || order.Name==Phase7Leg2) &&
                    (orderState==OrderState.Rejected || orderState==OrderState.Cancelled) &&
                    !phase7CancelRequested && !phase7AnyEntryFilled)
                {
                    phase7CancelRequested=true;
                    TriggerCustomEvent(_ => CancelPhase7Entries("entry rejected/cancelled"), null);
                }
            }
            R43Diagnostic("ORDER_"+orderState.ToString(),"name="+order.Name+" error="+error+" comment="+comment);
            if(orderState==OrderState.Rejected || error!=ErrorCode.NoError)
                R43Diagnostic("ORDER_REJECTED","order="+order.Name+" state="+orderState+" error="+error+" comment="+comment);
            else if(orderState==OrderState.Accepted || orderState==OrderState.Working)
                R43Diagnostic("ORDER_"+orderState.ToString().ToUpperInvariant(),"order="+order.Name);
            PublishOrderState(orderState.ToString(),
                "order="+order.Name+"; qty="+quantity+"; filled="+filled+
                "; avg="+averageFillPrice.ToString(System.Globalization.CultureInfo.InvariantCulture)+
                "; error="+error);
        }
        protected override void OnExecutionUpdate(Execution execution, string executionId,
            double price, int quantity, MarketPosition marketPosition, string orderId,
            DateTime time)
        {
            if(State!=State.Realtime || execution==null)return;
            if (phase7TwoLegActive && execution.Order != null)
            {
                if (execution.Order.Name==Phase7Leg1 || execution.Order.Name==Phase7Leg2)
                {
                    if (execution.Order.OrderAction == (phase7Direction>0 ? OrderAction.Buy : OrderAction.SellShort))
                    {
                        phase7AnyEntryFilled=true;
                        WriteForwardFill(execution,price,quantity,time);
                        if(execution.Order.Name==Phase7Leg2)
                            phase8RunnerFillPrice=execution.Order.AverageFillPrice>0?
                                execution.Order.AverageFillPrice:price;
                    }
                    else if (execution.Order.Name==Phase7Leg1)
                        phase7Tp1Filled=true;
                    else if (execution.Order.Name==Phase7Leg2)
                        phase7Tp2Filled=true;
                }
            }
            if (phase7TwoLegActive && execution.Order != null &&
                execution.Order.FromEntrySignal == Phase7Leg1 &&
                execution.Order.Name == "Profit target" &&
                execution.Order.OrderAction == (phase7Direction > 0 ? OrderAction.Sell : OrderAction.BuyToCover) &&
                !phase7BreakevenMoved && Position.MarketPosition != MarketPosition.Flat &&
                !double.IsNaN(phase8RunnerFillPrice))
            {
                phase7BreakevenMoved = true;
                // Do not move stop past entry if the actual runner entry filled at a different price.
                SetStopLoss(Phase7Leg2, CalculationMode.Price, phase8RunnerFillPrice, false);
                PublishOrderState("BREAKEVEN_REQUESTED", "runner stop="+phase8RunnerFillPrice);
            }
            R43Diagnostic("EXECUTION","order="+orderId+" qty="+quantity+" price="+price);
            PublishOrderState("EXECUTION",
                "order="+orderId+"; qty="+quantity+"; price="+
                price.ToString(System.Globalization.CultureInfo.InvariantCulture)+
                "; position="+marketPosition);
        }
        // All TEM instances share this folder. Serialize heartbeat publication and
        // clean up the staging file even if Windows rejects a replacement.
        private static readonly object HeartbeatWriteSync = new object();
        private static void WriteHeartbeatAtomic(string destination, string payload)
        {
            if (string.IsNullOrEmpty(destination)) return;
            string temporary = destination + "." + Guid.NewGuid().ToString("N") + ".tmp";
            lock (HeartbeatWriteSync)
            {
                try
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(destination));
                    File.WriteAllText(temporary, payload);
                    if (File.Exists(destination))
                        File.Replace(temporary, destination, null);
                    else
                        File.Move(temporary, destination);
                }
                finally
                {
                    try { if (File.Exists(temporary)) File.Delete(temporary); }
                    catch (IOException) { /* Diagnostics are emitted by caller. */ }
                    catch (UnauthorizedAccessException) { /* Do not mask write failure. */ }
                }
            }
        }

        private DateTime lastManagementCheck = DateTime.MinValue;
        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "Traderefy Execution Manager";
                FtrPendingAtrMultiple=1.5;
                FtrPendingCycleMinutes=27;
                Description = "SIM/Playback-only two-leg order bridge for Traderefy Ultimate System.";
                Calculate = Calculate.OnEachTick;
                EntriesPerDirection = 2; // Two separately named one-contract entries.
                EntryHandling = EntryHandling.UniqueEntries;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds = 30;
                StartBehavior = StartBehavior.WaitUntilFlat;
                RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
                BarsRequiredToTrade = 1;
                IsUnmanaged = false;
            }
            else if (State == State.DataLoaded)
            {
                bridgeDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
                    "NinjaTrader 8", "tus_sim_bridge");
                commandFile = Path.Combine(bridgeDir, "command.txt");
                if(Phase10ExactAccount && Instrument!=null)
                {
                    string key=AutoKey();
                    autoCommandFile=Path.Combine(bridgeDir,"auto_command_"+key+".txt");
                    autoHeartbeatFile=Path.Combine(bridgeDir,"auto_heartbeat_"+key+".txt");
                }
                Directory.CreateDirectory(bridgeDir);
                heartbeatFile = Path.Combine(bridgeDir, "heartbeat.txt");
                if(Account!=null && Instrument!=null)
                    accountHeartbeatFile=Path.Combine(bridgeDir,"account_heartbeat_"+
                        Account.Name+"_"+Instrument.FullName.Replace(" ","_").Replace("/","_")+".txt");
                managementFile = Path.Combine(bridgeDir, "management.txt");
                statusFile = Path.Combine(bridgeDir, "order_status.txt");
                if(Account!=null && Instrument!=null)
                    scopedStatusFile=Path.Combine(bridgeDir,"order_status_"+
                        Account.Name+"_"+Instrument.FullName.Replace(" ","_").Replace("/","_")+".txt");
            }
            else if (State == State.Realtime)
            {
                // Account assignment may become available only after DataLoaded.
                if(Phase10ExactAccount && Instrument!=null && autoCommandFile==null)
                {
                    string key=AutoKey();
                    autoCommandFile=Path.Combine(bridgeDir,"auto_command_"+key+".txt");
                    autoHeartbeatFile=Path.Combine(bridgeDir,"auto_heartbeat_"+key+".txt");
                }
                if(Account!=null && Instrument!=null)
                    accountHeartbeatFile=Path.Combine(bridgeDir,"account_heartbeat_"+
                        Account.Name+"_"+Instrument.FullName.Replace(" ","_").Replace("/","_")+".txt");
                if(Account!=null && Instrument!=null)
                    scopedStatusFile=Path.Combine(bridgeDir,"order_status_"+
                        Account.Name+"_"+Instrument.FullName.Replace(" ","_").Replace("/","_")+".txt");
                                R43Diagnostic("STRATEGY_REALTIME","account="+(Account==null?"null":Account.Name)+
                    " instrument="+(Instrument==null?"null":Instrument.FullName)+" family="+PlaybackFamily);
                heartbeatTimer = new Timer(_ =>
                {
                    try
                    {
                        if (Account == null || Instrument == null ||
                            !IsAllowedTradeSimulationAccount(Account.Name)) return;
                        // Publish scoped heartbeats first. Each write has its own
                        // finally cleanup so a failed replace cannot leak .tmp files.
                        string payload = DateTime.UtcNow.Ticks + "|" + Account.Name + "|" + Instrument.FullName;
                        if (accountHeartbeatFile != null)
                            WriteHeartbeatAtomic(accountHeartbeatFile, payload);
                        if (IsPlaybackAutoReady() && autoHeartbeatFile == null && Instrument != null)
                        {
                            string key = AutoKey();
                            autoCommandFile = Path.Combine(bridgeDir, "auto_command_" + key + ".txt");
                            autoHeartbeatFile = Path.Combine(bridgeDir, "auto_heartbeat_" + key + ".txt");
                        }
                        if (Phase10ExactAccount && autoHeartbeatFile != null)
                            WriteHeartbeatAtomic(autoHeartbeatFile, payload);
                        WriteHeartbeatAtomic(heartbeatFile, payload);
                    }
                    catch (Exception ex) { Print("TUS SIM heartbeat error: " + ex.Message); }
                }, null, 0, 2000);
            }
            else if (State == State.Terminated)
            {
                if (heartbeatTimer != null) { heartbeatTimer.Dispose(); heartbeatTimer = null; }
                // Do not delete shared heartbeat.txt: another TEM instance may still be active.
                try { if (autoHeartbeatFile != null && File.Exists(autoHeartbeatFile)) File.Delete(autoHeartbeatFile); } catch { }
                try { if (accountHeartbeatFile != null && File.Exists(accountHeartbeatFile)) File.Delete(accountHeartbeatFile); } catch { }
            }
        }
        private static bool IsPending(Order o)
        {
            return o!=null && (o.OrderState==OrderState.Working ||
                o.OrderState==OrderState.Accepted || o.OrderState==OrderState.Submitted ||
                o.OrderState==OrderState.PartFilled || o.OrderState==OrderState.ChangePending);
        }
        private void CancelPhase7Entries(string reason)
        {
            if (!phase7TwoLegActive) return;
            if (IsPending(phase7EntryOrder1)) CancelOrder(phase7EntryOrder1);
            if (IsPending(phase7EntryOrder2)) CancelOrder(phase7EntryOrder2);
            PublishOrderState("P7_CANCEL_REQUESTED",reason);
        }
        private void MonitorPhase7()
        {
            if (!phase7TwoLegActive) return;
            // R51: FTR pending entries expire by swing extension or market cycle,
            // never by a 30-second resting-order timeout.
            bool expired=false;
            if(!phase8IbsEntry && !phase7CancelRequested &&
                (IsPending(phase7EntryOrder1) || IsPending(phase7EntryOrder2)))
            {
                // OnEachTick: use the observed tick, not the entire forming bar's
                // high/low, which can include a pre-signal excursion.
                bool extension=!double.IsNaN(r51FtrExtensionPrice) &&
                    (phase7Direction>0 ? Close[0]>=r51FtrExtensionPrice :
                                         Close[0]<=r51FtrExtensionPrice);
                // Chart timestamps work in Playback; wall-clock timestamps do not.
                bool cycle=r51FtrSwingTime!=DateTime.MinValue &&
                    Time[0]>=r51FtrSwingTime.AddMinutes(FtrPendingCycleMinutes);
                bool adverse=phase7Direction>0?Close[0]<=phase7StopPrice:Close[0]>=phase7StopPrice;
                expired=extension || cycle || adverse;
                if(expired)R54Trace("TEM_FTR_PENDING_INVALIDATED",phase7ActiveCommandId,forwardSignalId,
                    "direction="+phase7Direction+" last="+Close[0]+" entry="+phase7EntryPrice+
                    " stop="+phase7StopPrice+" extension="+r51FtrExtensionPrice+
                    " swingTime="+r51FtrSwingTime.ToString("o")+
                    " extensionHit="+extension+" cycleHit="+cycle+" stopHit="+adverse);
                if(expired)R43Diagnostic("R51_FTR_PENDING_INVALIDATED",
                    "extension="+extension+" cycle="+cycle+" stop="+adverse+
                    " level="+r51FtrExtensionPrice+" swingTime="+r51FtrSwingTime.ToString("o"));
            }
            if(phase8IbsEntry && !phase7CancelRequested && !phase7AnyEntryFilled &&
                !double.IsNaN(phase8InvalidationPrice) &&
                (phase7Direction>0 ? High[0]>=phase8InvalidationPrice || Low[0]<=phase7StopPrice :
                                      Low[0]<=phase8InvalidationPrice || High[0]>=phase7StopPrice))
            {
                phase7CancelRequested=true;
                R43Diagnostic("R46_IBS_UNFILLED_INVALIDATED", "direction="+phase7Direction+
                    " high="+High[0]+" low="+Low[0]+" cancel200="+phase8InvalidationPrice+
                    " stop="+phase7StopPrice+" entry="+phase7EntryPrice);
                CancelPhase7Entries("IBS reached 200% extension or protective stop before fill");
            }
            if (!phase7CancelRequested && expired &&
                (IsPending(phase7EntryOrder1) || IsPending(phase7EntryOrder2)))
            {
                phase7CancelRequested=true;
                CancelPhase7Entries("FTR swing extension / 27-minute market cycle / stop invalidation");
            }
            // Clear the one-shot latch only after orders are terminal and account is flat.
            // A cancellation request is asynchronous: do not reset while either entry is pending.
            if (Position.MarketPosition==MarketPosition.Flat &&
                !IsPending(phase7EntryOrder1) && !IsPending(phase7EntryOrder2) &&
                (phase7CancelRequested || phase7AnyEntryFilled) &&
                (DateTime.UtcNow-phase7SubmittedUtc).TotalSeconds>1)
            {
                // Exit orders may still be in flight; don't automatically re-arm on the same bar.
                bool hasWorkingOrders=false;
                foreach (Order o in Orders)
                    if (IsPending(o)) {hasWorkingOrders=true;break;}
                if (!hasWorkingOrders)
                {
                    phase7TwoLegActive=false;
                    phase8IbsEntry=false;phase8SignalBar=-1;phase8InvalidationPrice=double.NaN;
                    r51FtrExtensionPrice=double.NaN;r51FtrSwingTime=DateTime.MinValue;
                    phase7ActiveCommandId="";
                    phase7AnyEntryFilled=false;
                    phase7CancelRequested=false;
                    phase7BreakevenMoved=false;
                    phase8RunnerFillPrice=double.NaN;
                    phase7EntryOrder1=null;
                    phase7EntryOrder2=null;
                    PublishOrderState("P7_COMPLETE","flat and no working strategy orders");
                }
            }
        }
        private void ProcessManagementRequest()
        {
            if ((DateTime.UtcNow-lastManagementCheck).TotalMilliseconds<300) return;
            lastManagementCheck=DateTime.UtcNow;
            if (!File.Exists(managementFile)) return;
            string processing=Path.Combine(bridgeDir,"processing_manage_"+Guid.NewGuid().ToString("N")+".txt");
            try { File.Move(managementFile,processing); }
            catch(IOException) { return; }
            try
            {
                string[] p=File.ReadAllText(processing).Trim().Split('|');
                long ticks;
                if((p.Length!=5 && p.Length!=6) || p[0]==lastManagementId || !long.TryParse(p[1],out ticks) ||
                   Math.Abs((DateTime.UtcNow-new DateTime(ticks,DateTimeKind.Utc)).TotalSeconds)>30 ||
                   !string.Equals(p[2],Account.Name,StringComparison.OrdinalIgnoreCase) ||
                   !string.Equals(p[3],Instrument.FullName,StringComparison.OrdinalIgnoreCase) ||
                   (p[4]!="CANCEL" && p[4]!="FLATTEN" && p[4]!="CANCEL_ENTRY"))
                { Print("TUS management rejected: invalid/expired/mismatched request"); return; }
                // Telegram CANCEL ENTRY carries the exact P7 command ID.
                // Reject stale buttons when a different trade is now active.
                if(p[4]=="CANCEL_ENTRY" && p.Length==6 &&
                    (!phase7TwoLegActive ||
                     !string.Equals(p[5],phase7ActiveCommandId,StringComparison.Ordinal)))
                { Print("TUS CANCEL_ENTRY rejected: old or inactive trade ID");
                  PublishOrderState("P7_CANCEL_REJECTED","old or inactive trade ID");return; }
                lastManagementId=p[0];
                if(p[4]=="CANCEL_ENTRY")
                {
                    // Never cancel a filled position's protective stop/target.
                    // Cancel only the two uniquely named P7 pending entry orders.
                    if(phase7TwoLegActive)phase7CancelRequested=true;
                    CancelPhase7Entries("manual cancel pending entries");
                    PublishOrderState("P7_ENTRY_CANCEL_REQUESTED","manual SIM cancel; filled position preserved");
                    Print("TUS CANCEL_ENTRY requested; existing filled position and protective exits preserved.");
                    return;
                }
                if (phase7TwoLegActive) phase7CancelRequested=true;
                // Only orders owned by this strategy; never cancels orders belonging to other strategies.
                foreach(Order order in Orders.ToArray())
                {
                    if(order==null)continue;
                    if(order.OrderState==OrderState.Working || order.OrderState==OrderState.Accepted ||
                       order.OrderState==OrderState.Submitted || order.OrderState==OrderState.PartFilled)
                        CancelOrder(order);
                }
                if(p[4]=="FLATTEN")
                {
                    if(Position.MarketPosition==MarketPosition.Long)
                        ExitLong("TUS_REMOTE_FLATTEN","TUS_SIM_ENTRY");
                    else if(Position.MarketPosition==MarketPosition.Short)
                        ExitShort("TUS_REMOTE_FLATTEN","TUS_SIM_ENTRY");
                }
                Print("TUS management request processed: "+p[4]+" account="+Account.Name+
                      " instrument="+Instrument.FullName+" (verify fills/order states)");
            }
            catch(Exception ex){Print("TUS management error: "+ex.Message);}
            finally{try{File.Delete(processing);}catch{}}
        }
        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0 || State != State.Realtime || Account == null ||
                !IsAllowedTradeSimulationAccount(Account.Name) || Instrument == null)
                return;
            if(IsPlaybackAutoReady() && autoCommandFile==null && Instrument!=null)
            {
                string key=AutoKey();
                autoCommandFile=Path.Combine(bridgeDir,"auto_command_"+key+".txt");
                autoHeartbeatFile=Path.Combine(bridgeDir,"auto_heartbeat_"+key+".txt");
            }
            ProcessManagementRequest();
            MonitorPhase7();
            if (Position.MarketPosition != MarketPosition.Flat) return;
            if ((DateTime.UtcNow - lastCheck).TotalMilliseconds < 300) return;
            lastCheck = DateTime.UtcNow;
            bool phase10Auto=Phase10ExactAccount && autoCommandFile!=null && File.Exists(autoCommandFile);
            string selectedCommand=phase10Auto?autoCommandFile:commandFile;
            if(IsPlaybackAccount() && !IsPlaybackAutoReady())return;
            if (!File.Exists(selectedCommand)) return;
            R43Diagnostic("COMMAND_DETECTED",Path.GetFileName(selectedCommand));
            string processing = Path.Combine(bridgeDir, "processing_" + Guid.NewGuid().ToString("N") + ".txt");
            try { File.Move(selectedCommand, processing); }
            catch (IOException) { return; }
            try
            {
                string[] parts = File.ReadAllText(processing).Trim().Split('|');
                if(parts.Length>=14 && parts[0]=="P8" && parts[12]=="FTR")
                    R54Trace("TEM_COMMAND_CONSUMED",parts[1],parts.Length>15?parts[15]:"",
                        "account="+parts[3]+" instrument="+parts[4]+" side="+parts[5]+
                        " entry="+parts[6]+" stop="+parts[7]+" tp1="+parts[8]+
                        " tp2="+parts[9]+" signalTicks="+parts[13]+
                        " rawFields="+parts.Length);
                if ((parts.Length == 14 || parts.Length == 16 || parts.Length == 19) && parts[0] == "P8")
                {
                    // P8|id|utcTicks|account|instrument|BUY/SELL|entry|stop|tp1|tp2|riskCapUsd|ttl|IBS/FTR|signalTimeTicks
                    // Versioned command, only on SIM, only a 2-lot LIMIT retracement.
                    long stamp,signalTicks; double entry, stop, tp1, tp2, cap; int ttl;
                    var inv=System.Globalization.CultureInfo.InvariantCulture;
                    if (parts[1]==lastId || !long.TryParse(parts[2],out stamp) ||
                        !double.TryParse(parts[6],System.Globalization.NumberStyles.Float,inv,out entry) ||
                        !double.TryParse(parts[7],System.Globalization.NumberStyles.Float,inv,out stop) ||
                        !double.TryParse(parts[8],System.Globalization.NumberStyles.Float,inv,out tp1) ||
                        !double.TryParse(parts[9],System.Globalization.NumberStyles.Float,inv,out tp2) ||
                        !double.TryParse(parts[10],System.Globalization.NumberStyles.Float,inv,out cap) ||
                        !int.TryParse(parts[11],out ttl) || ttl<1 || ttl>60 ||
                        (parts[12]!="IBS" && parts[12]!="FTR") ||
                        !long.TryParse(parts[13],out signalTicks) || signalTicks<=0 ||
                         (!IsPlaybackAccount() && signalTicks>DateTime.Now.AddMinutes(2).Ticks) ||
                        Math.Abs((DateTime.UtcNow-new DateTime(stamp,DateTimeKind.Utc)).TotalSeconds)>ttl ||
                        !string.Equals(parts[3],Account.Name,StringComparison.OrdinalIgnoreCase) ||
                        !string.Equals(parts[4],Instrument.FullName,StringComparison.OrdinalIgnoreCase) ||
                        (parts[5]!="BUY" && parts[5]!="SELL") || cap<=0 || cap>100000 ||
                        entry<=0 || stop<=0 || tp1<=0 || tp2<=0 || TickSize<=0 ||
                        Position.MarketPosition!=MarketPosition.Flat || phase7TwoLegActive)
                    { if(parts[12]=="FTR")R54Trace("TEM_COMMAND_REJECTED",parts[1],parts.Length>15?parts[15]:"",
                        "invalid/expired/duplicate/route/busy; lastId="+lastId+
                        " position="+Position.MarketPosition+" active="+phase7TwoLegActive+
                        " ageSeconds="+(long.TryParse(parts[2],out stamp)?(DateTime.UtcNow-new DateTime(stamp,DateTimeKind.Utc)).TotalSeconds.ToString("0.0"):"bad stamp"));
                      R43Diagnostic("COMMAND_REJECTED","invalid/expired/duplicate, wrong account/instrument, or strategy busy"+
                        " commandAccount="+(parts.Length>3?parts[3]:"missing")+
                        " strategyAccount="+(Account==null?"null":Account.Name)+
                        " commandInstrument="+(parts.Length>4?parts[4]:"missing")+
                        " strategyInstrument="+Instrument.FullName+
                        " position="+Position.MarketPosition+" active="+phase7TwoLegActive); return; }
                    bool ignoreAccountRisk=parts.Length>=16 && parts[14]=="IGNORE_ACCOUNT_RISK";
                    if(ignoreAccountRisk && (!phase10Auto ||
                       (Account.Name!="SimIBS" && Account.Name!="SimFTR" && !IsPlaybackAutoReady())))
                    {R43Diagnostic("RISK_OVERRIDE_REJECTED","wrong account or auto route");return;}
                    bool buy=parts[5]=="BUY";
                    // Trade Control must run on the M5 execution chart. Resolve the
                    // signal's original M5 bar to prevent approvals extending its life.
                    int signalBar=-1;
                    if(phase10Auto &&
                        (parts[3]!=(IsPlaybackAccount()?"Playback101":parts[12]=="IBS"?"SimIBS":"SimFTR") ||
                         (IsPlaybackAccount() && (!IsPlaybackAutoReady() || parts[12]!=PlaybackFamily)) ||
                         (parts[12]=="IBS" && (BarsPeriod.BarsPeriodType!=NinjaTrader.Data.BarsPeriodType.Minute || BarsPeriod.Value!=5)) ||
                         (parts[12]=="FTR" && (BarsPeriod.BarsPeriodType!=NinjaTrader.Data.BarsPeriodType.Tick || BarsPeriod.Value!=699))))
                    {R43Diagnostic("ROUTE_REJECTED","account / M5 or 699 tick series mismatch");return;}
                    if(parts[12]=="IBS")
                    {
                        if(BarsPeriod.BarsPeriodType!=NinjaTrader.Data.BarsPeriodType.Minute ||
                           BarsPeriod.Value!=5)
                        {R43Diagnostic("IBS_SERIES_REJECTED","Trade Control must be M5");return;}
                        signalBar=Bars.GetBar(new DateTime(signalTicks));
                        if(signalBar<0 || CurrentBar<signalBar)
                        {R43Diagnostic("IBS_SIGNAL_BAR_MISSING","Signal time cannot be found in chart bars");PublishOrderState("IBS_REJECTED","signal bar unavailable");return;}
                        // Do not create a new entry after its 200% extension or stop was
                        // touched on any bar after the original signal.
                        for(int absolute=signalBar+1;absolute<=CurrentBar;absolute++)
                        {
                            int ago=CurrentBar-absolute;
                            if(buy ? High[ago]>=tp2 || Low[ago]<=stop :
                                     Low[ago]<=tp2 || High[ago]>=stop)
                            {
                                R43Diagnostic("IBS_INVALIDATED","TP2 or stop touched before order submission");
                                PublishOrderState("IBS_INVALIDATED","200% extension or stop reached before submission");
                                return;
                            }
                        }
                    }
                    double r51Swing=double.NaN,r51Atr=double.NaN;
                    long r51SwingTicks=0;
                    if(parts[12]=="FTR" &&
                       (parts.Length!=19 ||
                        !double.TryParse(parts[16],System.Globalization.NumberStyles.Float,inv,out r51Swing) ||
                        !double.TryParse(parts[17],System.Globalization.NumberStyles.Float,inv,out r51Atr) ||
                        !long.TryParse(parts[18],out r51SwingTicks) ||
                        r51Swing<=0 || r51Atr<=0 || r51SwingTicks<=0 ||
                        r51SwingTicks>signalTicks ||
                        (buy?r51Swing>=entry:r51Swing<=entry)))
                    {R43Diagnostic("R51_FTR_METADATA_REJECTED","Missing/invalid 699 swing ATR/time");return;}
                    if(parts[12]=="FTR")
                    {
                        DateTime swingTime=new DateTime(r51SwingTicks);
                        double extension=Instrument.MasterInstrument.RoundToTickSize(
                            r51Swing+(buy?1:-1)*FtrPendingAtrMultiple*r51Atr);
                        // Completed bars strictly after the signal are safe to inspect.
                        // The forming signal bar's High/Low may predate the signal;
                        // use the current observed tick for that bar instead.
                        int ftrSignalBar=Bars.GetBar(new DateTime(signalTicks));
                        if(ftrSignalBar<0 || ftrSignalBar>CurrentBar)
                        {R43Diagnostic("R52_FTR_SIGNAL_BAR_MISSING","cannot validate signal history");return;}
                        bool priorExtension=false,priorStop=false;
                        for(int absolute=ftrSignalBar+1;absolute<CurrentBar;absolute++)
                        {
                            int ago=CurrentBar-absolute;
                            priorExtension |= buy?High[ago]>=extension:Low[ago]<=extension;
                            priorStop |= buy?Low[ago]<=stop:High[ago]>=stop;
                            if(priorExtension || priorStop)break;
                        }
                        bool currentExtension=buy?Close[0]>=extension:Close[0]<=extension;
                        bool currentStop=buy?Close[0]<=stop:Close[0]>=stop;
                        bool cycle=Time[0]>=swingTime.AddMinutes(FtrPendingCycleMinutes);
                        R54Trace("TEM_FTR_VALIDATION",parts[1],parts.Length>15?parts[15]:"",
                            "direction="+(buy?"LONG":"SHORT")+" signalTime="+new DateTime(signalTicks).ToString("o")+
                            " swingTime="+swingTime.ToString("o")+" swing="+r51Swing+" atr="+r51Atr+
                            " extension="+extension+" stop="+stop+" last="+Close[0]+
                            " signalBar="+ftrSignalBar+" currentBar="+CurrentBar+
                            " priorExtension="+priorExtension+" priorStop="+priorStop+
                            " currentExtension="+currentExtension+" currentStop="+currentStop+
                            " cycle="+cycle+" cycleMinutes="+FtrPendingCycleMinutes+
                            " result="+(priorExtension||priorStop||currentExtension||currentStop||cycle?"REJECT":"PASS"));
                        if(priorExtension || priorStop || currentExtension || currentStop || cycle)
                        {R43Diagnostic("R51_FTR_ALREADY_INVALID",
                            "priorExtension="+priorExtension+" priorStop="+priorStop+
                            " currentExtension="+currentExtension+" currentStop="+currentStop+
                            " cycle="+cycle+" last="+Close[0]+" extension="+extension+
                            " stop="+stop+" signalBar="+ftrSignalBar);return;}
                    }
                    // R45: defense-in-depth rounding for commands from any producer.
                    // Validate order geometry and account risk against the rounded prices.
                    double originalEntry=entry, originalStop=stop, originalTp1=tp1, originalTp2=tp2;
                    entry=Instrument.MasterInstrument.RoundToTickSize(entry);
                    stop=Instrument.MasterInstrument.RoundToTickSize(stop);
                    tp1=Instrument.MasterInstrument.RoundToTickSize(tp1);
                    tp2=Instrument.MasterInstrument.RoundToTickSize(tp2);
                    if(entry!=originalEntry || stop!=originalStop || tp1!=originalTp1 || tp2!=originalTp2)
                        R43Diagnostic("R45_TICK_ROUNDED","entry="+originalEntry+"->"+entry+
                            " stop="+originalStop+"->"+stop+" tp1="+originalTp1+"->"+tp1+
                            " tp2="+originalTp2+"->"+tp2);
                    if (buy ? !(stop<entry && entry<tp1 && tp1<tp2 && entry<=Close[0]) :
                              !(stop>entry && entry>tp1 && tp1>tp2 && entry>=Close[0]))
                    { R43Diagnostic("PRICE_REJECTED","Entry/SL/TP geometry or marketable limit; entry="+entry+" stop="+stop+" tp1="+tp1+" tp2="+tp2+" close="+Close[0]); return; }
                    double risk=Math.Abs(entry-stop)*Instrument.MasterInstrument.PointValue*2;
                    if (risk<=0 ||
                        (!ignoreAccountRisk && risk>cap) ||
                        new[]{entry,stop,tp1,tp2}.Any(x=>Math.Abs(x/TickSize-Math.Round(x/TickSize))>0.00001))
                    { R43Diagnostic("TICK_OR_RISK_REJECTED","risk="+risk+" cap="+cap+" override="+ignoreAccountRisk+" tick="+TickSize); return; }
                    forwardSetup=parts[12]=="FTR" && parts.Length>=16 && parts[15].Contains("FTR-") ?
                        "FTR-"+parts[15].Split(new[]{"FTR-"},StringSplitOptions.None).Last().Split('_')[0] : parts[12];
                    forwardRiskMode=ignoreAccountRisk?"IGNORE ACCOUNT RISK":"NORMAL";
                    forwardSignalId=parts.Length>=16?parts[15]:"";
                    lastId=parts[1]; phase7ActiveCommandId=parts[1]; phase7TwoLegActive=true;phase7BreakevenMoved=false;
                    phase7AnyEntryFilled=false;phase7CancelRequested=false;
                    phase8RunnerFillPrice=double.NaN;
                    phase7SubmittedUtc=DateTime.UtcNow;phase7ExpirySeconds=ttl;
                    phase8IbsEntry=parts[12]=="IBS";phase8SignalBar=signalBar;
                    phase8InvalidationPrice=phase8IbsEntry?tp2:double.NaN;
                    r51FtrExtensionPrice=phase8IbsEntry?double.NaN:
                        Instrument.MasterInstrument.RoundToTickSize(
                            r51Swing+(buy?1:-1)*FtrPendingAtrMultiple*r51Atr);
                    r51FtrSwingTime=phase8IbsEntry?DateTime.MinValue:new DateTime(r51SwingTicks);
                    phase7EntryOrder1=null;phase7EntryOrder2=null;
                    phase7EntryPrice=entry;phase7StopPrice=stop;phase7Direction=buy?1:-1;
                    SetStopLoss(Phase7Leg1,CalculationMode.Price,stop,false);
                    SetStopLoss(Phase7Leg2,CalculationMode.Price,stop,false);
                    SetProfitTarget(Phase7Leg1,CalculationMode.Price,tp1);
                    SetProfitTarget(Phase7Leg2,CalculationMode.Price,tp2);
                    if(buy){EnterLongLimit(0,true,1,entry,Phase7Leg1);EnterLongLimit(0,true,1,entry,Phase7Leg2);}
                    else {EnterShortLimit(0,true,1,entry,Phase7Leg1);EnterShortLimit(0,true,1,entry,Phase7Leg2);}
                    if(parts[12]=="FTR")R54Trace("TEM_FTR_LIMIT_REQUESTED",parts[1],forwardSignalId,
                        "side="+(buy?"LONG":"SHORT")+" entry="+entry+" stop="+stop+
                        " tp1="+tp1+" tp2="+tp2+" extension="+r51FtrExtensionPrice+
                        " swingTime="+r51FtrSwingTime.ToString("o"));
                    R43Diagnostic("R46_RESTING_LIMIT_SUBMITTED",parts[12]+" signal="+new DateTime(signalTicks)+
                        " direction="+(buy?"LONG":"SHORT")+" entry50="+entry+
                        " confirmed100="+tp1+" cancel200="+(phase8IbsEntry?tp2:double.NaN)+
                        " stop="+stop+" noIBSTimeExpiry="+phase8IbsEntry);
                    R43Diagnostic("LIMIT_REQUESTED",parts[12]+" entry="+entry+" stop="+stop+" tp1="+tp1+" tp2="+tp2);
                    PublishOrderState("LIMIT_REQUESTED",parts[12]+" 2 contracts; entry="+entry+"; stop="+stop+"; tp1="+tp1+"; tp2="+tp2);
                    return;
                }
                if (parts.Length != 8) { Print("TUS SIM rejected: invalid request."); return; }
                // Phase 09: never mix manual market entries with an active managed two-leg plan.
                if (phase7TwoLegActive || Position.MarketPosition != MarketPosition.Flat ||
                    Orders.Any(o => IsPending(o)))
                { Print("TUS P9: manual SIM order blocked; active position or working orders."); return; }
                if (parts[0] == lastId) return;
                lastId = parts[0];
                long createdTicks;
                int qty, stopTicks, targetTicks;
                if (!long.TryParse(parts[1], out createdTicks) ||
                    Math.Abs((DateTime.UtcNow - new DateTime(createdTicks, DateTimeKind.Utc)).TotalSeconds) > 30 ||
                    !string.Equals(parts[2], Account.Name, StringComparison.OrdinalIgnoreCase) ||
                    !string.Equals(parts[3], Instrument.FullName, StringComparison.OrdinalIgnoreCase) ||
                    !int.TryParse(parts[5], out qty) || !int.TryParse(parts[6], out stopTicks) ||
                    !int.TryParse(parts[7], out targetTicks) || qty < 1 || qty > 2 ||
                    stopTicks < 1 || targetTicks < 1 || stopTicks > 1000 || targetTicks > 1000 ||
                    (parts[4] != "BUY" && parts[4] != "SELL"))
                { Print("TUS SIM rejected: expired, mismatched, or invalid request."); return; }
                // Managed strategy places protective stop/target for the entry signal.
                string signal = "TUS_SIM_ENTRY";
                SetStopLoss(signal, CalculationMode.Ticks, stopTicks, false);
                SetProfitTarget(signal, CalculationMode.Ticks, targetTicks);
                if (parts[4] == "BUY") EnterLong(qty, signal);
                else EnterShort(qty, signal);
                Print("TUS SIM order requested: " + parts[4] + " " + qty + " " + Instrument.FullName +
                    " SL=" + stopTicks + " TP=" + targetTicks + " account=" + Account.Name);
            }
            catch (Exception ex) { Print("TUS SIM bridge error: " + ex.Message); }
            finally { try { File.Delete(processing); } catch { } }
        }
    }
}
